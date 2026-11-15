"""Load synthetic firms and matters (scripts/output/matters.json) into the database.

Idempotent: existing firms (by slug) and matters (by case number) are left untouched,
so it is safe to run on every `docker compose up`.

Usage:
  uv run python -m app.cli.seed --data ../scripts/output/matters.json
"""

import argparse
import json
import os
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.auth import hash_password
from app.db.models import Firm, Matter, User
from app.db.session import get_sessionmaker


def seed(data: dict[str, list[dict[str, str]]], password: str) -> dict[str, int]:
    created = {"firms": 0, "matters": 0, "users": 0}
    with get_sessionmaker()() as session:
        firms: dict[str, Firm] = {}
        for f in data["firms"]:
            firm = session.scalars(select(Firm).where(Firm.slug == f["slug"])).one_or_none()
            if firm is None:
                firm = Firm(slug=f["slug"], name=f["name"])
                session.add(firm)
                session.flush()
                created["firms"] += 1
            firms[f["slug"]] = firm

        for m in data["matters"]:
            firm = firms[m["firm_slug"]]
            exists = session.scalars(
                select(Matter).where(
                    Matter.firm_id == firm.id, Matter.case_number == m["case_number"]
                )
            ).one_or_none()
            if exists is not None:
                continue
            session.add(
                Matter(
                    firm_id=firm.id,
                    case_number=m["case_number"],
                    title=m["title"],
                    client_name=m["client_name"],
                    defendant=m["defendant"],
                    incident_date=date.fromisoformat(m["incident_date"]),
                    opened_at=date.fromisoformat(m["opened_at"]),
                )
            )
            created["matters"] += 1
        for slug, firm in firms.items():
            email = f"paralegal@{slug}.test"
            if session.scalars(select(User).where(User.email == email)).one_or_none() is None:
                session.add(
                    User(
                        firm_id=firm.id,
                        email=email,
                        full_name=f"{firm.name} Paralegal",
                        password_hash=hash_password(password),
                    )
                )
                created["users"] += 1
        session.commit()

        for slug in firms:
            print(f"login: paralegal@{slug}.test / <SEED_PASSWORD>")
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("../scripts/output/matters.json"))
    args = parser.parse_args()
    # Demo users' password comes from the environment, never from the repo.
    password = os.environ.get("SEED_PASSWORD", "")
    if len(password) < 8:
        raise SystemExit("Set SEED_PASSWORD (min 8 chars) for the demo users")
    print(seed(json.loads(args.data.read_text(encoding="utf-8")), password))


if __name__ == "__main__":
    main()
