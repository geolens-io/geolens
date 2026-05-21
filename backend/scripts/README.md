# Backend scripts

One-shot maintenance scripts for the GeoLens backend. Each script is
meant to be run from `backend/` as the working directory.

## Alembic clean-DB upgrade test

**Script:** `test_alembic_upgrade_clean_db.sh`

Runs `alembic upgrade head` against a freshly-initialized, throwaway
PostGIS container. This is the semantic complement to the syntactic
`down_revision` linkage check that v1015's close-gate ran — confirms
the full migration chain (0001 → latest) actually applies without error
on a clean DB, not just that the revision graph is well-formed.

The script builds the project's custom `./db` image (PostGIS + pgvector)
and mounts `scripts/init-db.sh` into `/docker-entrypoint-initdb.d/` so
the `postgis`, `pg_trgm`, `vector`, and `unaccent` extensions are present
before alembic runs (the `0001_baseline.py` migration asserts these
extensions exist and refuses to run without them).

### Prerequisites

- Docker daemon running locally (the script spins up a container and
  builds the project's `./db` image).
- `uv` installed (alembic runs through `uv run --no-dev`).
- No other process listening on port `54399` (override with
  `ALEMBIC_TEST_DB_PORT` if the default collides). The script refuses
  to start if the port is busy — a stale container or local postgres
  on that port would silently mask migration failures.

### Usage

```bash
cd backend && ./scripts/test_alembic_upgrade_clean_db.sh
```

Exits 0 on success, non-zero with diagnostics (container logs tail) on
failure. The throwaway container is `docker rm -f`'d on every exit path,
including Ctrl-C and unexpected signals (via `trap cleanup EXIT INT TERM`).

#### Env overrides

| Variable                | Default | Purpose                              |
| ----------------------- | ------- | ------------------------------------ |
| `ALEMBIC_TEST_DB_PORT`  | `54399` | Host port for the throwaway DB       |
| `ALEMBIC_TEST_TIMEOUT`  | `60`    | DB-readiness poll timeout in seconds |

### When to run

- At every milestone close-gate (Phase XXXX-CLOSE) after the last
  migration lands and before the version tag is cut.
- When adding a new migration to v1016-and-later phases — local
  smoke before pushing the PR.
- Suspected migration-chain rot (e.g. an out-of-order `down_revision`
  that the linkage check missed because both sides referenced the same
  revision).

### Limitations

- Tests the schema-only path. Data migrations that depend on existing
  rows (rare in this repo; the convention is "expand/contract DDL with
  no row-mutation") would need a fixture step before `upgrade head`.
- Does NOT run the application after migration — only confirms alembic
  exits 0. Application boot is exercised by the existing pytest
  `test_db_session` fixture and by `docker compose up`.
- The `POSTGIS_IMAGE_TAG` constant in the script (currently `17-3.5`)
  documents the base image the test container is layered on top of.
  The script builds the local `./db` image, so the resulting test
  image always tracks `db/Dockerfile`'s `FROM` line — but if you bump
  `db/Dockerfile`, also bump the `POSTGIS_IMAGE_TAG` comment in the
  script to keep the documentation honest.
- First run takes ~2-3 minutes to compile pgvector inside the image
  build. Subsequent runs are seconds (cache hit on the `./db` image).
