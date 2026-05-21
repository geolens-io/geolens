---
name: 260508-d6i-CONTEXT
description: Locked decisions for the env-reset + thematic-demo seed + full smoke-check quick task
type: context
---

# Quick Task 260508-d6i: Reset local env + load demo data + run smoke-check.md - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Task Boundary

Do a complete reset of the local environment (rebuild containers, destroy volumes), load the demo data, then run the smoke-check.md flow and report any issues.

In scope:
- Stop running stack and destroy named docker volumes
- Rebuild + start the stack from scratch
- Seed demo data via the chosen script
- Verify health, then run the chosen smoke scope
- Capture results into the SUMMARY.md

Out of scope:
- Fixing any smoke failures inline (report-only)
- Wiping `cache/` directory (preserve e2e fixture cache)
- Pruning the docker build cache
- Modifying source code
- Editing seed scripts or tests

</domain>

<decisions>
## Implementation Decisions

### Compose stack
- **Main stack only** — `docker compose up -d --build` with the default `docker-compose.yml`. Do NOT layer `docker-compose.demo.yml`. Hot-reload + dev bind mounts stay enabled, no auto-reset service runs.

### Reset depth
- **Volumes only** — `docker compose down -v` followed by `docker compose up -d --build`. Destroys the four named volumes (`geolens_pgdata`, `geolens_tile_cache`, `geolens_upload_staging`, `geolens_backup_data`). Preserves the `cache/` directory (Natural Earth fixture archives used by E2E tests) and the docker image layer cache.

### Demo data loader
- **`scripts/demo/seed-thematic-demo.py`** — same script the demo overlay would have invoked. Loads themed sample maps + datasets. Run it manually after the stack is healthy.

### Smoke check scope
- **Full** — `npm run e2e:smoke` (core + builder + fixtures). Matches the default scope documented in `.claude/commands/smoke-check.md`.

### Smoke failure handling
- **Report only, stop** — Per `smoke-check.md`: do not modify test files, do not auto-fix. Capture failing test names + one-line reasons into the SUMMARY.md and end the task. User triages from there.

### Claude's Discretion
- Wait-for-healthy strategy (poll `/health` endpoint vs fixed sleep) — pick the most reliable approach.
- Whether to run `alembic upgrade head` explicitly post-up, or trust the api container's startup hook to do it.
- Whether to log raw stdout from the seeder for debugging vs summarize.
- Whether to capture `docker compose logs` snippets when smoke fails.

</decisions>

<specifics>
## Specific Ideas

- `.claude/commands/smoke-check.md` is the canonical procedure: preflight `curl -sf http://localhost:8080/health`, then `npm run e2e:smoke` from project root. Report-only on failure.
- The four named volumes to destroy are listed in `docker volume ls`: `geolens_backup_data`, `geolens_pgdata`, `geolens_tile_cache`, `geolens_upload_staging`.
- Currently no containers are running (verified via `docker compose ps` at task start), so the down step is a no-op for service shutdown but still needed to clean volume references.
- `cache/` contains `e2e-natural-earth/`, `ne_10m_admin_0_countries.zip`, `ne_10m_reefs.zip` — preserve.

</specifics>

<canonical_refs>
## Canonical References

- `.claude/commands/smoke-check.md` — full smoke-check procedure (PHASE 0 preflight, PHASE 1 commands by scope, PHASE 2 reporting format)
- `docker-compose.yml` — main compose stack
- `scripts/demo/seed-thematic-demo.py` — thematic demo seeder
- `package.json` — `e2e:smoke` script chain (core + builder + fixtures)
- `README.md` — references the standard `docker compose up -d` startup flow

</canonical_refs>
