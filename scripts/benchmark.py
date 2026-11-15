"""End-to-end benchmark: upload synthetic PDFs through the API and measure throughput.

For each firm in the manifest it logs in, uploads that firm's documents, then polls until
every document reaches a final status (filed / needs_review / failed). It reports
documents per second and checks the results against the manifest's ground truth.

Usage (stack running, seed loaded, SEED_PASSWORD exported):
  uv run --project backend python scripts/benchmark.py --data scripts/output

Compare 1 vs N workers:
  docker compose up -d --scale worker=1   ->  run the benchmark
  docker compose up -d --scale worker=4   ->  run it again (re-generate with a new --seed
                                              first: duplicates are deduplicated, not reprocessed)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

FINAL = {"filed", "needs_review", "failed"}


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/token", data={"username": email, "password": password})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def upload(client: httpx.Client, headers: dict[str, str], path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        resp = client.post(
            "/documents",
            headers=headers,
            files={"file": (path.name, fh, "application/pdf")},
        )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--data", type=Path, default=Path("scripts/output"))
    parser.add_argument("--concurrency", type=int, default=8, help="parallel uploads")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    password = os.environ.get("SEED_PASSWORD")
    if not password:
        raise SystemExit("Export SEED_PASSWORD (same value used by the seed)")

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    matters = json.loads((args.data / "matters.json").read_text(encoding="utf-8"))["matters"]

    with httpx.Client(base_url=args.api, timeout=60) as client:
        headers_by_firm = {
            slug: login(client, f"paralegal@{slug}.test", password)
            for slug in {e["firm_slug"] for e in manifest}
        }
        case_by_matter_id = {
            m["id"]: m["case_number"]
            for slug, headers in headers_by_firm.items()
            for m in client.get("/matters", headers=headers).json()
        }

        started = time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as pool:
            uploads = list(
                pool.map(
                    lambda e: (
                        e,
                        upload(
                            client,
                            headers_by_firm[e["firm_slug"]],
                            args.data / e["file"],
                        ),
                    ),
                    manifest,
                )
            )
        upload_seconds = time.perf_counter() - started
        duplicates = sum(1 for _, r in uploads if r["duplicate"])

        pending = {r["document"]["id"]: e for e, r in uploads}
        results: dict[str, dict[str, Any]] = {}
        while pending and time.perf_counter() - started < args.timeout:
            time.sleep(1)
            for doc_id, entry in list(pending.items()):
                doc = client.get(
                    f"/documents/{doc_id}", headers=headers_by_firm[entry["firm_slug"]]
                ).json()
                if doc["status"] in FINAL:
                    results[doc_id] = doc
                    del pending[doc_id]
        total_seconds = time.perf_counter() - started

    statuses = Counter(d["status"] for d in results.values())
    by_id = {r["document"]["id"]: e for e, r in uploads}
    type_ok = sum(1 for i, d in results.items() if d["doc_type"] == by_id[i]["doc_type"])
    filed = [(i, d) for i, d in results.items() if d["status"] == "filed"]
    matter_ok = sum(
        1 for i, d in filed if case_by_matter_id.get(d["matter_id"]) == by_id[i]["case_number"]
    )

    print(f"documents:          {len(manifest)} ({duplicates} duplicates skipped by dedup)")
    print(f"upload time:        {upload_seconds:.1f}s")
    print(f"end-to-end time:    {total_seconds:.1f}s")
    print(f"throughput:         {len(results) / total_seconds:.2f} docs/s (client view)")
    # Server-side view: first upload -> last document finished, from DB timestamps. This
    # excludes the client's polling granularity, so it is the number to compare.
    # Duplicates are excluded: dedup returns the *old* document, with its old timestamps.
    fresh = [results[r["document"]["id"]] for _, r in uploads if not r["duplicate"]]
    first = min(datetime.fromisoformat(d["created_at"]) for d in fresh)
    last = max(datetime.fromisoformat(d["updated_at"]) for d in fresh)
    server_seconds = (last - first).total_seconds()
    print(f"server throughput:  {len(fresh) / server_seconds:.2f} docs/s ({server_seconds:.1f}s)")
    print(f"final statuses:     {dict(statuses)}  (still pending: {len(pending)})")
    print(f"doc type accuracy:  {type_ok}/{len(results)}")
    print(f"auto-filed correct: {matter_ok}/{len(filed)} matched to the right case")
    _ = matters  # loaded for reference / future checks


if __name__ == "__main__":
    main()
