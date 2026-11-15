# Deploying DocIntake

`docker-compose.prod.yml` runs the whole stack on a single host (a VPS with Docker is
enough: 2 vCPU / 4 GB RAM handles the demo comfortably). Verified locally end-to-end:
2 API replicas behind nginx, 2 worker replicas, 500 documents processed.

## 1. Prepare the host

```bash
git clone https://github.com/LucaDepetris2/DocIntake.git && cd DocIntake
uv run --project backend python scripts/generate_fake_docs.py        # synthetic data
(cd backend && uv run python -m app.cli.train --data ../scripts/output)  # bakes the model into the image
```

## 2. Secrets (`.env.prod`, never committed)

Start from `.env.example` and replace every value. Generate secrets with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.

| Variable | Notes |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `DATABASE_URL` must use the same values |
| `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` | `BROKER_URL` must use the same values |
| `JWT_SECRET` | ≥ 32 bytes; the app **refuses to start** in production with the default or a short one |
| `SEED_PASSWORD` | password of the demo users created by the seed |
| `FLOWER_BASIC_AUTH`, `GRAFANA_ADMIN_PASSWORD` | |
| `WEB_PORT`, `GRAFANA_PORT` | optional, default 80 / 3000 |

## 3. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps \
  -v "$PWD/scripts/output:/seed:ro" api python -m app.cli.seed --data /seed/matters.json
```

Only nginx (web + `/api`) and Grafana publish ports. Postgres, RabbitMQ, Flower and
Prometheus stay on the internal Docker network; reach them with an SSH tunnel, e.g.
`ssh -L 15672:localhost:15672` after temporarily publishing the port, or
`docker compose exec`.

## 4. Operate

- **Scale**: `deploy.replicas` for `api` and `worker` (Prometheus discovers replicas via DNS).
- **Logs**: JSON on stdout — `docker compose logs api worker | grep <correlation-id>`.
- **Failed documents**: visible in the UI (`Failed` filter, Retry button); their messages
  are kept in RabbitMQ's `documents.dlq`.
- **Migrations**: run automatically by the one-shot `migrate` service before API/workers.
- **Backups**: the `pgdata` and `storage` volumes hold all state.

## Before real (non-synthetic) data

This is a portfolio deployment. Handling real PHI would additionally require TLS (e.g. a
Caddy/Traefik front with Let's Encrypt), encryption at rest for the storage volume, object
storage instead of a local volume, Postgres Row-Level Security (see ADR 0003), audit log
retention, and a BAA with every provider involved.
