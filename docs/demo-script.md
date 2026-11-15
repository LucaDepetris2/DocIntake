# 2-minute demo script

Setup before recording: stack running (`docker compose up -d`), seed loaded, browser tabs
open on the UI (:8080), Grafana (:3000) and RabbitMQ (:15672); a terminal in the repo root;
a fresh batch generated (`scripts/generate_fake_docs.py --doc-seed 999 --out scripts/output-demo`).

| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | README architecture diagram | "Law firms receive hundreds of medical records, bills and court filings a day. DocIntake reads them, figures out what they are and which case they belong to, and files them — or asks a human when it isn't sure." |
| 0:15–0:35 | UI: upload ~10 PDFs; the inbox refreshes as statuses change | "Upload returns immediately. FastAPI stores the file and publishes the document id to RabbitMQ; Celery workers run five stages: OCR, classification, entity extraction, case matching and filing." |
| 0:35–0:55 | Open a filed document: PDF preview, type + confidence, entities, timeline, filed path | "Every status change is recorded. The file got the firm's naming rule and folder, and a discovery request created a 30-day response deadline." |
| 0:55–1:15 | Review queue → open one → confirm the pre-selected case | "Low confidence goes to review, pre-filled with the pipeline's best guess. Confirming runs only the filing stage." |
| 1:15–1:35 | Terminal: `scripts/benchmark.py` with 500 docs; then Grafana dashboard | "Under load: 500 documents in ~14 seconds with four workers. Grafana shows stage throughput, latency and outcomes." |
| 1:35–1:50 | Upload a corrupt PDF → `Failed` with sanitized error; RabbitMQ UI → `documents.dlq` has 1 message | "Transient errors are retried with backoff; permanent ones are dead-lettered and can be retried from the UI. Every stage is idempotent, so redeliveries are safe." |
| 1:50–2:00 | `docker compose logs … \| grep <correlation-id>` | "One correlation id follows an upload across the API and every worker — no document content in the logs." |
