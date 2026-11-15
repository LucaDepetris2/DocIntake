# ADR 0001 — Celery + RabbitMQ for the processing pipeline

- Status: accepted
- Date: 2026-11-15

## Context

Processing a document takes from ~50 ms to several seconds (OCR). Uploads must return
immediately, processing must survive worker crashes, and throughput must scale by adding
workers. Failures need retries for transient problems and a place to park poison messages.

## Options

1. **FastAPI `BackgroundTasks`** — runs in the API process. No durability (lost on restart),
   no retries, no horizontal scaling. Fine for e-mails, not for a pipeline.
2. **Celery + Redis** — simple to run; Redis as a broker lacks native dead-lettering and
   its visibility-timeout semantics make long tasks awkward.
3. **Celery + RabbitMQ** — durable queues, per-message acks, native dead-letter exchanges,
   a management UI. Celery adds retries with backoff, chains, Flower.
4. **A workflow engine (Temporal, Prefect)** — strongest guarantees and visibility, but a
   much larger operational footprint than this project needs.
5. **Postgres as a queue (`SELECT … FOR UPDATE SKIP LOCKED`)** — one less service, but we
   would re-implement retries, backoff, routing and monitoring.

## Decision

Celery with RabbitMQ. Messages contain only the document id; all state is in Postgres
(no Celery result backend). Settings: `acks_late`, `prefetch_multiplier=1`,
`reject_on_worker_lost`, `acks_on_failure_or_timeout=False` (so permanent failures are
dead-lettered), JSON serializer only.

## Consequences

- At-least-once delivery ⇒ every stage **must** be idempotent (status guard +
  compare-and-set + unique constraints). This is tested, including a concurrency race.
- Two more services to run (RabbitMQ, Flower). Acceptable with docker compose.
- Celery only declares the queues a worker consumes; the DLQ is declared explicitly on
  `worker_ready`, otherwise dead-lettered messages are silently dropped (found during
  end-to-end testing).
- `correlation_id` is an AMQP property Celery fills with the task id, so our tracing header
  is named `x_correlation_id`.
