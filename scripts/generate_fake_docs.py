"""Generate synthetic legal/medical PDFs for DocIntake (no real PHI, ever).

Outputs (default: scripts/output/):
  matters.json   firms + their matters (loaded by scripts/seed.py)
  manifest.json  one entry per PDF with the ground truth (doc_type, firm, case_number)
  pdf/*.pdf      the documents

Some documents are deliberately "dirty" to exercise the pipeline:
  - no case number and/or misspelled client names  -> fuzzy matching / needs_review
  - image-only pages (scanned)                      -> OCR fallback

Usage (from repo root):
  uv run --project backend python scripts/generate_fake_docs.py --n 140 --seed 42
"""

from __future__ import annotations

import argparse
import io
import json
import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from faker import Faker
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

DOC_TYPES = (
    "medical_record",
    "medical_bill",
    "pleading",
    "correspondence",
    "discovery_request",
    "lien_notice",
    "other",
)

FIRMS = (
    {"slug": "harbor-law", "name": "Harbor & Pine Injury Law"},
    {"slug": "summit-legal", "name": "Summit Legal Group"},
)

PROVIDERS = (
    "Riverside Orthopedic Associates",
    "Mercy General Hospital",
    "Lakeview Physical Therapy",
    "Northside Imaging Center",
    "Valley Chiropractic Clinic",
    "St. Anne Emergency Medicine",
)
DIAGNOSES = (
    ("S13.4XXA", "Sprain of ligaments of cervical spine"),
    ("S33.5XXA", "Sprain of ligaments of lumbar spine"),
    ("M54.2", "Cervicalgia"),
    ("S83.511A", "Sprain of anterior cruciate ligament of right knee"),
    ("S06.0X0A", "Concussion without loss of consciousness"),
)
CPT = (
    ("99284", "Emergency department visit, high severity"),
    ("72141", "MRI cervical spine without contrast"),
    ("97110", "Therapeutic exercises, each 15 minutes"),
    ("98941", "Chiropractic manipulative treatment, 3-4 regions"),
    ("20610", "Arthrocentesis, major joint"),
)
COURTS = (
    "SUPERIOR COURT OF THE STATE OF CALIFORNIA, COUNTY OF LOS ANGELES",
    "UNITED STATES DISTRICT COURT, CENTRAL DISTRICT OF CALIFORNIA",
    "CIRCUIT COURT OF COOK COUNTY, ILLINOIS",
    "DISTRICT COURT OF HARRIS COUNTY, TEXAS",
)
INSURERS = ("Allied Mutual Insurance", "Keystone Casualty", "Pioneer Auto Insurance")
LIENHOLDERS = (
    "Medicare Secondary Payer Recovery Contractor",
    "BlueStar Health Plan Subrogation Unit",
    "State Medicaid Recovery Program",
)


@dataclass
class Matter:
    firm_slug: str
    case_number: str
    title: str
    client_name: str
    defendant: str
    incident_date: str
    opened_at: str


@dataclass
class ManifestEntry:
    file: str
    firm_slug: str
    doc_type: str
    case_number: str | None  # expected matter (ground truth)
    has_case_number: bool
    misspelled_client: bool
    image_only: bool


def _fmt(d: date) -> str:
    return d.strftime("%B %d, %Y")


def _misspell(rng: random.Random, name: str) -> str:
    chars = list(name)
    idx = [i for i, c in enumerate(chars) if c.isalpha() and i > 0]
    for i in rng.sample(idx, k=min(2, len(idx))):
        chars[i] = rng.choice("aeiourstln")
    return "".join(chars)


def make_matters(fake: Faker, rng: random.Random, per_firm: int) -> list[Matter]:
    matters: list[Matter] = []
    for firm in FIRMS:
        for _ in range(per_firm):
            client = fake.name()
            defendant = rng.choice([fake.name(), fake.company()])
            incident = fake.date_between(start_date="-3y", end_date="-6m")
            year = incident.year % 100
            if rng.random() < 0.5:
                case_number = f"{rng.randint(1, 9)}:{year:02d}-cv-{rng.randint(1000, 99999):05d}"
            else:
                case_number = f"{incident.year}-L-{rng.randint(100000, 999999)}"
            matters.append(
                Matter(
                    firm_slug=firm["slug"],
                    case_number=case_number,
                    title=f"{client} v. {defendant}",
                    client_name=client,
                    defendant=defendant,
                    incident_date=incident.isoformat(),
                    opened_at=(incident + timedelta(days=rng.randint(5, 60))).isoformat(),
                )
            )
    return matters


# ---------------------------------------------------------------------------
# Content templates: each returns a list of lines (one page worth of text)
# ---------------------------------------------------------------------------


def _ref_line(m: Matter, with_case: bool, rng: random.Random) -> str:
    if not with_case:
        return f"Re: {m.title}" if rng.random() < 0.5 else f"Patient/Client: {m.client_name}"
    return f"Re: {m.title}, Case No. {m.case_number}"


def medical_record(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    provider = rng.choice(PROVIDERS)
    visit = date.fromisoformat(m.incident_date) + timedelta(days=rng.randint(0, 120))
    code, dx = rng.choice(DIAGNOSES)
    lines = [
        provider.upper(),
        rng.choice(["PROGRESS NOTE", "CLINICAL NOTE", "OFFICE VISIT NOTE", "DISCHARGE SUMMARY"]),
        f"Patient: {client}    DOB: {_fmt(fake.date_of_birth(minimum_age=20, maximum_age=75))}",
        f"Date of Service: {_fmt(visit)}",
        f"Attending Physician: Dr. {fake.name()}, MD",
        "",
        "CHIEF COMPLAINT:",
        rng.choice(
            [
                "Neck pain and stiffness following motor vehicle collision.",
                "Low back pain radiating to the left leg after a fall.",
                "Right knee pain and swelling after the incident.",
            ]
        ),
        "HISTORY OF PRESENT ILLNESS:",
        f"Patient reports onset of symptoms on {_fmt(date.fromisoformat(m.incident_date))}.",
        f"Pain rated {rng.randint(3, 9)}/10. Patient denies prior injury to the area.",
        "PHYSICAL EXAMINATION:",
        "Tenderness to palpation with reduced range of motion. Vital signs stable.",
        "ASSESSMENT / DIAGNOSIS:",
        f"{code} - {dx}",
        "PLAN:",
        rng.choice(
            [
                "Physical therapy 3x/week for 6 weeks. Follow-up in 4 weeks.",
                "MRI ordered. Prescribed NSAIDs. Return if symptoms worsen.",
                "Referral to orthopedic surgeon. Work restrictions issued.",
            ]
        ),
    ]
    if wc:
        lines.insert(4, f"Attorney reference: {m.case_number}")
    return lines


def medical_bill(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    provider = rng.choice(PROVIDERS)
    start = date.fromisoformat(m.incident_date) + timedelta(days=rng.randint(0, 60))
    lines = [
        provider.upper(),
        rng.choice(["ITEMIZED STATEMENT", "PATIENT BILLING STATEMENT", "STATEMENT OF CHARGES"]),
        f"Account #: {rng.randint(10_000_000, 99_999_999)}    "
        f"Statement Date: {_fmt(start + timedelta(days=45))}",
        f"Patient: {client}",
        f"Guarantor: {client}    Insurance: {rng.choice(INSURERS)}",
        "",
        "DATE OF SERVICE   CPT    DESCRIPTION                                   CHARGE",
    ]
    total = 0.0
    for i in range(rng.randint(3, 7)):
        code, desc = rng.choice(CPT)
        amount = round(rng.uniform(85, 4200), 2)
        total += amount
        dos = start + timedelta(days=i * rng.randint(2, 9))
        lines.append(f"{dos.strftime('%m/%d/%Y')}        {code}  {desc[:42]:<42}  ${amount:,.2f}")
    paid = round(total * rng.uniform(0, 0.4), 2)
    lines += [
        "",
        f"TOTAL CHARGES: ${total:,.2f}",
        f"Payments/Adjustments: -${paid:,.2f}",
        f"BALANCE DUE: ${total - paid:,.2f}",
        "Please remit payment within 30 days. Amount due upon receipt.",
    ]
    if wc:
        lines.insert(5, f"Claim/Case Reference: {m.case_number}")
    return lines


def pleading(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    title = rng.choice(
        [
            "COMPLAINT FOR DAMAGES",
            "ANSWER TO COMPLAINT",
            "MOTION TO COMPEL",
            "NOTICE OF MOTION AND MOTION FOR SUMMARY JUDGMENT",
        ]
    )
    filed = date.fromisoformat(m.opened_at) + timedelta(days=rng.randint(10, 300))
    hearing = filed + timedelta(days=rng.randint(21, 90))
    return [
        rng.choice(COURTS),
        "",
        f"{client.upper()},",
        "                Plaintiff,",
        "        v.",
        f"{m.defendant.upper()},",
        "                Defendant.",
        "",
        f"Case No. {m.case_number}" if wc else "Case No. ____________",
        title,
        "",
        f"Plaintiff {client}, by and through undersigned counsel, hereby alleges as follows:",
        "1. This Court has jurisdiction over the parties and the subject matter.",
        f"2. On {_fmt(date.fromisoformat(m.incident_date))}, Defendant negligently caused the",
        "   collision resulting in serious bodily injury to Plaintiff.",
        "3. As a direct and proximate result, Plaintiff suffered damages in excess of the",
        "   jurisdictional minimum of this Court.",
        "WHEREFORE, Plaintiff prays for judgment against Defendant.",
        f"Hearing Date: {_fmt(hearing)} at 9:00 a.m., Department {rng.randint(1, 60)}",
        f"Dated: {_fmt(filed)}",
        f"Respectfully submitted, {fake.name()}, Esq., Attorney for Plaintiff",
    ]


def correspondence(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    sent = date.fromisoformat(m.opened_at) + timedelta(days=rng.randint(5, 200))
    return [
        rng.choice(INSURERS + PROVIDERS).upper(),
        fake.address().replace("\n", ", "),
        "",
        _fmt(sent),
        "",
        rng.choice(["VIA EMAIL AND U.S. MAIL", "VIA FACSIMILE", "VIA CERTIFIED MAIL"]),
        _ref_line(m, wc, rng).replace("Patient/Client", "Our Insured/Claimant"),
        f"Claim No.: {rng.randint(100000, 999999)}-{rng.randint(10, 99)}",
        "",
        "Dear Counsel:",
        rng.choice(
            [
                f"We are in receipt of your letter regarding your client, {client}.",
                f"Thank you for your correspondence concerning {client}'s claim.",
                f"This letter follows our telephone conversation regarding {client}.",
            ]
        ),
        rng.choice(
            [
                "Please forward the outstanding medical records at your earliest convenience.",
                "We are currently reviewing the demand and will respond shortly.",
                "Kindly confirm whether your client is still treating.",
            ]
        ),
        "Should you have any questions, please do not hesitate to contact me.",
        "",
        "Sincerely,",
        fake.name(),
        rng.choice(["Claims Adjuster", "Senior Claims Specialist", "Records Custodian"]),
    ]


def discovery_request(
    fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool
) -> list[str]:
    kind = rng.choice(
        [
            "SPECIAL INTERROGATORIES, SET ONE",
            "REQUEST FOR PRODUCTION OF DOCUMENTS, SET ONE",
            "REQUESTS FOR ADMISSION, SET ONE",
        ]
    )
    served = date.fromisoformat(m.opened_at) + timedelta(days=rng.randint(30, 300))
    return [
        rng.choice(COURTS),
        f"{client} v. {m.defendant}",
        f"Case No. {m.case_number}" if wc else "",
        "",
        f"PROPOUNDING PARTY: Defendant {m.defendant}",
        f"RESPONDING PARTY: Plaintiff {client}",
        f"SET NO.: {kind}",
        "",
        "Pursuant to the applicable Code of Civil Procedure, Defendant requests that",
        "Plaintiff respond to the following under oath within thirty (30) days of service.",
        "INTERROGATORY NO. 1: State all injuries you claim resulted from the incident.",
        "INTERROGATORY NO. 2: Identify each health care provider who examined you.",
        "REQUEST NO. 3: Produce all documents evidencing medical expenses claimed.",
        "REQUEST NO. 4: Admit that you were not wearing a seatbelt at the time.",
        f"Date of Service: {_fmt(served)}",
        f"PROOF OF SERVICE: served by mail on {_fmt(served)}",
        f"{fake.name()}, Attorney for Defendant",
    ]


def lien_notice(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    holder = rng.choice(LIENHOLDERS + PROVIDERS)
    amount = round(rng.uniform(1500, 85000), 2)
    sent = date.fromisoformat(m.opened_at) + timedelta(days=rng.randint(30, 400))
    return [
        holder.upper(),
        rng.choice(["NOTICE OF LIEN", "NOTICE OF MEDICAL LIEN", "CONDITIONAL PAYMENT NOTICE"]),
        _fmt(sent),
        "",
        _ref_line(m, wc, rng),
        f"Beneficiary/Patient: {client}",
        f"Date of Incident: {_fmt(date.fromisoformat(m.incident_date))}",
        "",
        f"PLEASE TAKE NOTICE that {holder} asserts a lien in the amount of ${amount:,.2f}",
        "against any settlement, judgment or award obtained on behalf of the above-named",
        "patient for treatment rendered as a result of the incident.",
        "No settlement proceeds may be disbursed without satisfaction of this lien.",
        "Please notify our office before any settlement is finalized.",
        f"Lien Reference No.: LN-{rng.randint(100000, 999999)}",
        fake.name(),
        "Recovery Specialist",
    ]


def other(fake: Faker, rng: random.Random, m: Matter, client: str, wc: bool) -> list[str]:
    return rng.choice(
        [
            [
                "PHOTOGRAPH LOG",
                f"Photos taken at scene, {fake.street_address()}",
                f"Taken by: {fake.name()}",
                "Photo 1: vehicle front bumper. Photo 2: intersection view.",
            ],
            [
                "MILEAGE REIMBURSEMENT LOG",
                f"Client: {client}",
                "Trips to treatment appointments: 14. Total miles: 312.",
            ],
            [
                "WAGE VERIFICATION FORM",
                f"Employer: {fake.company()}",
                f"Employee: {client}",
                f"Hourly rate: ${rng.randint(15, 60)}.00. Hours missed: {rng.randint(8, 400)}.",
            ],
            [
                "INTAKE QUESTIONNAIRE",
                f"Name: {client}",
                "How did you hear about us? Referral from a friend.",
                "Describe the incident briefly: rear-ended at a red light.",
            ],
        ]
    )


TEMPLATES = {
    "medical_record": medical_record,
    "medical_bill": medical_bill,
    "pleading": pleading,
    "correspondence": correspondence,
    "discovery_request": discovery_request,
    "lien_notice": lien_notice,
    "other": other,
}

# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def _render_text_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER, invariant=True)  # invariant -> reproducible bytes
    _width, height = LETTER
    y = height - 60
    c.setFont("Helvetica", 10)
    for line in lines:
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 60
        c.drawString(54, y, line)
        y -= 15
    c.showPage()
    c.save()
    return buf.getvalue()


def _render_image_pdf(lines: list[str]) -> bytes:
    """A 'scanned' page: the text is only present as pixels (needs OCR)."""
    img = Image.new("L", (1700, 2200), color=255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=30)
    y = 100
    for line in lines:
        draw.text((100, y), line, fill=0, font=font)
        y += 44
    png = io.BytesIO()
    img.save(png, format="PNG")
    png.seek(0)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER, invariant=True)
    _width, height = LETTER
    c.drawImage(ImageReader(png), 0, 0, width=_width, height=height)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------


def generate(
    out_dir: Path, n: int, seed: int, matters_per_firm: int, doc_seed: int | None = None
) -> dict[str, Any]:
    rng = random.Random(seed)
    fake = Faker("en_US")
    Faker.seed(seed)

    # Matters always come from `seed` (they must match what's loaded in the DB);
    # `doc_seed` produces a different batch of documents for the same matters.
    matters = make_matters(fake, rng, matters_per_firm)
    if doc_seed is not None and doc_seed != seed:
        rng = random.Random(doc_seed)
        Faker.seed(doc_seed)
    pdf_dir = out_dir / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[ManifestEntry] = []
    for i in range(n):
        doc_type = DOC_TYPES[i % len(DOC_TYPES)]  # balanced classes
        m = rng.choice(matters)
        with_case = rng.random() > 0.25
        misspelled = rng.random() < 0.15
        image_only = rng.random() < 0.08
        client = _misspell(rng, m.client_name) if misspelled else m.client_name

        lines = TEMPLATES[doc_type](fake, rng, m, client, with_case)
        data = _render_image_pdf(lines) if image_only else _render_text_pdf(lines)

        name = f"{i:04d}_{doc_type}.pdf"
        (pdf_dir / name).write_bytes(data)
        manifest.append(
            ManifestEntry(
                file=f"pdf/{name}",
                firm_slug=m.firm_slug,
                doc_type=doc_type,
                case_number=m.case_number,
                has_case_number=with_case,
                misspelled_client=misspelled,
                image_only=image_only,
            )
        )

    matters_doc = {"firms": list(FIRMS), "matters": [asdict(m) for m in matters]}
    (out_dir / "matters.json").write_text(json.dumps(matters_doc, indent=2), encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps([asdict(e) for e in manifest], indent=2), encoding="utf-8"
    )
    return {"documents": len(manifest), "matters": len(matters), "out": str(out_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "output")
    parser.add_argument("--n", type=int, default=140, help="number of documents")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--matters-per-firm", type=int, default=12)
    parser.add_argument(
        "--doc-seed", type=int, default=None, help="new documents for the same matters"
    )
    args = parser.parse_args()
    print(json.dumps(generate(args.out, args.n, args.seed, args.matters_per_firm, args.doc_seed)))


if __name__ == "__main__":
    main()
