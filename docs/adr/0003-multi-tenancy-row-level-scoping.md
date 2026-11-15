# ADR 0003 — Multi-tenancy by row-level scoping on `firm_id`

- Status: accepted
- Date: 2026-11-15

## Context

Several law firms share one deployment. A firm must never see another firm's documents,
matters or alerts — a leak would be a confidentiality (and HIPAA) incident.

## Options

1. **Database per tenant** — strongest isolation, but migrations, connections and backups
   multiply with every firm.
2. **Schema per tenant** — similar trade-offs, plus `search_path` juggling.
3. **Shared tables with a `firm_id` column, scoped in the application** — simplest to run;
   isolation depends on every query being scoped.
4. **Option 3 + Postgres Row-Level Security** — the database enforces the scoping even if
   a query forgets it.

## Decision

Option 3, with guard rails:

- The tenant is derived **only** from the authenticated user: the JWT carries `sub` and
  `firm_id`, and on each request the user is loaded and its `firm_id` must match the token
  (a token minted for another firm is rejected).
- Every repository function that reads tenant data takes `firm_id` as a parameter.
- Cross-tenant ids return **404**, not 403, so the API doesn't confirm that a resource exists.
- Writes are scoped too (e.g. a reviewer can't assign a document to another firm's matter).
- Upload dedup is per firm (`UNIQUE(firm_id, sha256)`): the same file sent by two firms
  creates two independent documents.
- Tests cover each of these cases.

## Consequences

- One forgotten `WHERE firm_id = …` would leak data. Mitigated by the repository layer and
  tests; Row-Level Security (option 4) is the natural next step as defence in depth.
- Internal components without a user (workers, metrics) operate across firms by design.
