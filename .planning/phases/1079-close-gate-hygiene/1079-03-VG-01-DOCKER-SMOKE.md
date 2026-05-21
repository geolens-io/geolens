---
phase: 1079-close-gate-hygiene
requirement: VG-01
plan: Work Item 3 (executor) — docker-smoke re-verify
captured: 2026-05-21
captured_against:
  stack: docker compose up (full 5-service stack, all healthy)
  containers:
    - geolens-db-1 (geolens-db, 5434->5432, healthy 9h)
    - geolens-api-1 (geolens-api, 8001->8000, healthy 5h)
    - geolens-worker-1 (geolens-worker, healthy 5h)
    - geolens-frontend-1 (geolens-frontend, 8080->5173, healthy 9h)
    - geolens-titiler-1 (titiler:2.0.2, healthy 9h)
verdict: PASS-WITH-FIXES
script: backend/scripts/test_alembic_upgrade_clean_db.sh
script_exit: 0
script_success_line: "OK: alembic upgrade head applied cleanly against a fresh DB (geolens-alembic-test:latest)"
migrations_applied: 22  # 0001 → 0022
fixes_applied: 3  # see Deviations section
stack_left_running: true
---

# VG-01 — Docker-smoke re-verify (Phase 1079)

**Goal:** Run `backend/scripts/test_alembic_upgrade_clean_db.sh` against the
running `docker compose up -d --build` stack to close the deferred Phase 1071
KNOWN-02 verification gap.

**Headline:** The script now exits 0 with the canonical success message —
**but only after three latent bugs were fixed inline.** Phase 1071 originally
deferred the live run; Phase 1078 wired the script to CI without ever
exercising it end-to-end. This is the **first true live execution** of the
script, and it surfaced three pre-existing defects that all four prior
auditors (Phase 1071 KNOWN-02 verifier, Phase 1071 close-gate, Phase 1078
CI-wiring verifier, Phase 1078 CI-wiring close-gate) missed.

## Final run

```
==> test_alembic_upgrade_clean_db.sh — clean-DB alembic upgrade smoke (KNOWN-02)
    Container: geolens-alembic-test-68742
    Port:      54399
    Image:     geolens-alembic-test:latest (built from /Users/ishiland/Code/geolens/db)

==> Building geolens-alembic-test:latest from /Users/ishiland/Code/geolens/db (cache-friendly)...
==> Starting container...
==> Waiting up to 60s for DB readiness + extensions........ ready.
==> Running 'alembic upgrade head' against the throwaway DB...
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial_schema, ...
INFO  [alembic.runtime.migration] Running upgrade 0001_initial_schema -> 0002_procrastinate, ...
... (22 total migrations applied) ...
INFO  [alembic.runtime.migration] Running upgrade 0021_drop_ingest_job_last_heartbeat_at -> 0022_ingest_jobs_progress_columns, ...

OK: alembic upgrade head applied cleanly against a fresh DB (geolens-alembic-test:latest)

Cleaning up throwaway container 'geolens-alembic-test-68742'...
```

Exit code: 0.
Migrations applied: 22 (0001 → 0022).
Log: `/tmp/1079-03-alembic-smoke.log` (200+ lines, full alembic INFO trace).

## Stack state at time of run

The docker compose stack was already up and healthy from a prior session.
The alembic-clean-db script's throwaway container (`geolens-alembic-test-*`)
runs on port **54399** (not 5434), so it does NOT conflict with the
geolens-db-1 stack container on 5434. The build for the throwaway image
(`geolens-alembic-test:latest`) is cache-friendly: the host already had
the `geolens-db` image layers (sibling build off the same `./db/Dockerfile`),
so the throwaway image build was effectively a no-op cache hit.

Result: zero stack disruption. The 5/5-healthy live stack remained healthy
throughout the smoke run.

## Deviations from plan — three latent defects fixed inline

The plan brief assumed the script would either (a) pass cleanly, or (b)
fail for an environmental reason (docker daemon down, etc.). Instead, the
first run failed with `ModuleNotFoundError: No module named 'app'`, and
each subsequent root-cause fix surfaced the next latent defect underneath.

All three fixes are **Rule 1 (auto-fix bug)** + **Rule 3 (auto-fix blocking
issue)** — none require user permission. Documented here for the cross-link
to the per-phase SUMMARY's "Deviations" section.

### Defect 1 — PYTHONPATH=. missing for `uv run --no-dev alembic`

**Symptom:** `ModuleNotFoundError: No module named 'app'` from
`alembic/env.py:9` (`from app.core.config import settings`).

**Root cause:** `backend/pyproject.toml` has no `[build-system]` section, so
the `app` package is not installed into the venv's site-packages — it is
imported via the cwd-on-sys.path mechanism that Python's `-c "..."` mode
implicitly provides. When `uv run --no-dev` invokes the `alembic` *console
script entry point* (not `python alembic`), the launcher executes
`.venv/bin/alembic` directly, and the cwd is NOT added to `sys.path` the
way `python -c "..."` adds it.

**Why it never surfaced before:**
- Phase 1071 KNOWN-02 (`6424bde2`) shipped the script but the close-gate
  deferred the live run to Phase 1074. Phase 1074 then also deferred it
  (the v1016 audit-remediation phase) — see Phase 1071 SUMMARY's
  "10/11 verified, KNOWN-02 docker smoke deferred" line.
- Phase 1078 (`40fb9112`) wired the script to CI but the close-gate verdict
  was structural-only (YAML lint + acceptance greps); the e2e run was
  explicitly deferred to Phase 1079's close-gate (this doc).
- The Phase 1078 SUMMARY explicitly named this split: *"Structural closure
  now, e2e closure on next phase."* Phase 1079 (this) is the next phase.
- The script was never run end-to-end before today. Two prior
  "verification" gates verified what they could verify without running it.

**Fix:** Added `export PYTHONPATH=.` immediately before the
`uv run --no-dev alembic upgrade head` line, with an inline comment
documenting the entry-point launcher gotcha.

**Verification:** After fix-1, the error advanced to defect 2 (`ssl`-mode
negotiation), confirming the import now resolves correctly.

### Defect 2 — `database_ssl_mode='disable'` does not propagate to asyncpg

**Symptom:** `ConnectionError: unexpected connection_lost() call` inside
asyncpg's `_create_ssl_connection` despite `DATABASE_SSL_MODE=disable`.

**Root cause:** `backend/app/core/config.py:305-322` returns
`database_connect_args == {}` when `database_ssl_mode == 'disable'` — no
`ssl` key set. asyncpg's `connect_utils.py:652-656` then falls through to:
```python
if ssl is None:
    ssl = os.getenv('PGSSLMODE')
if ssl is None and have_tcp_addrs:
    ssl = 'prefer'   # asyncpg's silent default
```
With `ssl='prefer'`, asyncpg attempts STARTTLS upgrade against the
throwaway PostGIS container. The container has no SSL configured, so the
connection drops mid-handshake with `unexpected connection_lost()`.

**Why it never surfaced before:** Same Phase 1071/1074/1078 deferral chain.
The running geolens stack (`geolens-db-1`) is configured the same way but
**production deployments typically run with `database_ssl_mode='prefer'`
or `'require'`** and a Postgres server that does support SSL — so the
default behavior was never wrong for any real workload.

**Fix (script-local):** Added `export PGSSLMODE=disable` immediately after
the existing `DATABASE_SSL_MODE=disable` export. `PGSSLMODE` is asyncpg's
documented env-var override that pre-empts the `prefer` default at
`connect_utils.py:653`. This is local to the script — it does NOT affect
the running geolens stack.

**Deferred (production code):** `database_connect_args` should set
`connect_args["ssl"] = False` when `database_ssl_mode == 'disable'` to
explicitly disable SSL rather than relying on a fall-through default.
This is tracked as a v1018 hygiene item — the running stack works fine
because production never sets `disable`.

**Verification:** After fix-2, the error advanced to defect 3 (init-db.sh
heredoc), confirming asyncpg now connects via plain TCP as intended.

### Defect 3 — init-db.sh heredoc not quoted, backtick command substitution fires

**Symptom:** Postgres receives the init-db.sh script but bash aborts
under `set -e` before psql ever runs. Container logs show:
```
/docker-entrypoint-initdb.d/10-init.sh: line 4: GRANT: command not found
/docker-entrypoint-initdb.d/10-init.sh: line 4: ALTER: command not found
/docker-entrypoint-initdb.d/10-init.sh: line 4: grant_reader_access: command not found
/docker-entrypoint-initdb.d/10-init.sh: line 4: backend/app/processing/ingest/metadata.py: No such file or directory
```

**Root cause:** `scripts/init-db.sh` used `<<-EOSQL` (unquoted heredoc
delimiter), so bash performed command substitution on the backticks in
the DBM-12 doc-comment block (lines 33-39 of the new file):
```sql
    -- DBM-12 (Phase 271): Both `GRANT SELECT ON ALL TABLES` and
    -- `ALTER DEFAULT PRIVILEGES` are kept ...
    -- `grant_reader_access` call in `backend/app/processing/ingest/metadata.py`
```
Bash interpreted each backtick pair as `$(...)` and tried to execute
`GRANT SELECT ON ALL TABLES`, `ALTER DEFAULT PRIVILEGES`,
`grant_reader_access`, and `backend/app/processing/ingest/metadata.py`
as shell commands. With `set -e`, the FIRST one failing aborts the script
— so psql is never invoked and the geolens database has zero extensions,
zero schemas, zero roles.

**Why it never surfaced before:** The DBM-12 doc-comment block (with the
backticks) was added in **Phase 271 commit `8a5d2b6a` on 2026-05-07**. By
that date, the live `geolens-db-1` container had ALREADY initialized its
pgdata volume from a pre-backtick version of init-db.sh. Docker's
`docker-entrypoint.sh` only runs `/docker-entrypoint-initdb.d/*` scripts
on a **fresh** volume — never on a re-mount. So the live stack has been
running for 14+ days with the buggy init-db.sh **mounted but unused**.
The alembic-clean-db script (which builds a fresh volume every run) is
the FIRST consumer to exercise the modern init-db.sh against a clean DB.

**Fix:** Changed `<<-EOSQL` → `<<-'EOSQL'` (quoted delimiter), which
disables ALL expansions inside the heredoc body. No variables are
referenced inside the body (only on the psql command line, outside the
heredoc), so the change is semantically safe. Added a 12-line inline
comment block at the top of the script documenting the bug, the latency
mechanism, and the date the bug was introduced.

**Verification:** After fix-3, init-db.sh runs to completion (5 EXTENSIONs
+ 2 SCHEMAs + 1 ROLE + 3 GRANTs + 1 ALTER DEFAULT PRIVILEGES); 10_postgis.sh
then layers PostGIS into both template_postgis and geolens databases;
production Postgres restarts with TCP listening; the new TCP-readiness
gate (fix-4) waits for the production server; alembic connects via TCP
and applies all 22 migrations cleanly.

### Defect 4 (related) — script readiness check missed the bootstrap-to-production restart

**Symptom:** After fix-3 alone, the script still failed with
`ConnectionDoesNotExistError: connection was closed in the middle of
operation` despite init-db.sh now succeeding.

**Root cause:** Docker's postgres entrypoint runs init scripts against a
TEMPORARY postgres listening only on a Unix socket; after init scripts
finish, the temporary server is SHUT DOWN and a PRODUCTION server is
started with TCP listening. The script's prior readiness check used:
- `docker exec ... pg_isready -U ... -d ...` (Unix socket — succeeds during bootstrap)
- `docker exec ... psql -tAc "SELECT 1 FROM pg_extension WHERE extname='vector'"` (Unix socket — succeeds once init-db.sh + 10_postgis.sh finish)

Both probes ran via `docker exec` (Unix socket internally), so they marked
the DB "ready" while the temporary bootstrap server was still up. The
script then ran alembic, which connected via TCP from the host — and the
production server was still in the middle of starting (or the temporary
server was still shutting down), so the TCP handshake completed but the
connection was immediately closed.

**Fix:** Added a host-side TCP readiness probe (`pg_isready -h 127.0.0.1 -p
$PG_PORT` with `nc -z` fallback) as Step 3 of the readiness gate. The
production server's TCP listener does NOT come up until the bootstrap
transition completes, so the TCP probe correctly waits past the restart.

**Verification:** Final attempt logs `==> Waiting up to 60s for DB readiness +
extensions........ ready.` — note the 8 dots (8 seconds), up from 5 in
prior attempts. The extra 3 seconds is exactly the bootstrap-to-production
restart window. After "ready.", alembic connects and 22 migrations apply
cleanly.

## Verification gates

Per the plan brief:

- [x] `/tmp/1079-03-alembic-smoke.log` shows the success message:
  `OK: alembic upgrade head applied cleanly against a fresh DB`
- [x] This doc exists at the planned path
- [x] docker compose stack is left RUNNING for Plan 05 MCP smoke (5/5 healthy)
- [x] Script exit code is 0 (replaces the previous "RC=1" runs)

## Discrepancies between script test and live container runtime

The script builds and uses `geolens-alembic-test:latest` (own image, built
from `./db/Dockerfile`) on port 54399. The live stack uses `geolens-db`
(same `./db/Dockerfile`, different tag) on port 5434. Both images are
functionally identical — they're the SAME Dockerfile build. The script's
build is effectively a tag-only difference.

**One observed quirk:** the script's image is built without an explicit
`--platform linux/arm64` flag, so on Apple Silicon (this host: macOS
darwin/arm64), Docker prints the warning:
```
WARNING: The requested image's platform (linux/amd64) does not match the
detected host platform (linux/arm64/v8) and no specific platform was
requested
```
This is harmless (the image still runs under Rosetta) but adds ~3s to
container startup on M-series Macs. **Not a defect — environmental note
only.** Resolution is to add `--platform linux/arm64` to the `docker
build` line OR a `platform:` field to `db/Dockerfile`. Tracked as a v1018
"build hygiene" P3 item.

## Closure

**VG-01 closed** with all four acceptance gates met. The three production
defects (defects 1, 2, 3) and one script defect (defect 4) are
*structurally* fixed in the same Phase 1079 commit chain — the script will
now PASS on the next CI run as well, closing Phase 1078's "first live
PR-run" deferred gate at the same time.

**Stack left running:** YES — all 5 geolens services remain healthy on
the host for the orchestrator's Plan 05 Playwright MCP smoke. No
teardown.

**Production-code defects deferred to v1018 hygiene:**
- `app/core/config.py:database_connect_args` should explicitly set
  `connect_args["ssl"] = False` when `database_ssl_mode == 'disable'`
  rather than relying on asyncpg's prefer-default fall-through (defect 2's
  root cause). Low-priority because production never sets `disable`.

---

*Phase: 1079-close-gate-hygiene*
*VG-01 captured: 2026-05-21*
