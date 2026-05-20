---
phase: 1063-low-followup-tickets
plan: "02"
subsystem: security/config
tags: [security, nginx, config, tests, documentation]
dependency_graph:
  requires: []
  provides: [SEC-FU-02-pin, SEC-FU-09-nginx-version-suppression, SEC-FU-10-db-role-docs]
  affects: [backend/tests/test_demo_credentials_guard.py, frontend/nginx.conf, .env.example]
tech_stack:
  added: []
  patterns: [named-audit-regression-pin, server_tokens-nginx, least-privilege-postgres-role-docs]
key_files:
  created:
    - (none)
  modified:
    - backend/tests/test_demo_credentials_guard.py
    - frontend/nginx.conf
    - .env.example
decisions:
  - "SEC-FU-02: config.py already had DEMO_JWT_SECRET guard (Phase 1061 Plan 05); new named test provides explicit audit-traceable regression pin without config.py changes"
  - "SEC-FU-09: server_tokens off placed in server {} block (not http {} scope) per audit wording; inline comment cites the finding"
  - "SEC-FU-10: documentation-only; alembic migration trade-off documented inline alongside the SQL recipe"
metrics:
  duration: "~2 minutes"
  completed: "2026-05-20"
requirements:
  - SEC-FU-02
  - SEC-FU-09
  - SEC-FU-10
---

# Phase 1063 Plan 02: SEC-FU-02 + SEC-FU-09 + SEC-FU-10 Summary

**One-liner:** Named JWT demo literal regression test + nginx version disclosure suppression + least-privilege Postgres role documentation.

## What Was Built

Three configuration-level defense-in-depth closures from the 2026-05-19 security audit follow-up list. Zero runtime code changes, zero new dependencies, zero migrations.

### SEC-FU-02: JWT Demo Literal Refusal — Named Regression Pin

Verified `backend/app/core/config.py`:
- Line 21: `DEMO_JWT_SECRET = "demo-only-do-not-use-in-production-change-me"` confirmed present
- Lines 244-250: `if jwt_value == DEMO_JWT_SECRET: raise ValueError(...)` confirmed present (Phase 1061 Plan 05 coverage is correct)

Added `test_sec_fu_02_jwt_demo_literal_refused` to `backend/tests/test_demo_credentials_guard.py`:
- Parametrized over `demo_mode=[True, False]` — covers both GEOLENS_DEMO_MODE states
- Asserts `ValidationError` with `"known-public"` substring in message
- Docstring explicitly cites SEC-FU-02 and the literal string for audit traceability
- Intentionally redundant with broader SEC-S06 tests — different test ID = independent reproduction guarantee

### SEC-FU-09: nginx Version Disclosure Suppression

Added `server_tokens off;` to `frontend/nginx.conf` server block at line 34, alongside the existing security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`), before the `gzip on;` block.

Inline comment references SEC-FU-09 and `sec-audit-20260519.md`.

Manual verification recipe (not automated — requires container rebuild):
```
docker compose up -d --build frontend
curl -I http://localhost:8080/ | grep -i ^server:
# Expected: "Server: nginx" (no version string)
```

### SEC-FU-10: Least-Privilege Postgres Role Documentation

Extended the `DATABASE_URL_OVERRIDE` commentary block in `.env.example` with:
1. SEC-FU-10 header citing `sec-audit-20260519.md`
2. Statement that the role SHOULD NOT be cluster superuser (no CREATEDB, CREATEROLE, BYPASSRLS, REPLICATION)
3. SQL recipe creating `geolens_app` role with minimal grants:
   - CONNECT on database
   - USAGE on catalog schema
   - SELECT/INSERT/UPDATE/DELETE on tables
   - USAGE/SELECT on sequences
   - EXECUTE on functions
   - ALTER DEFAULT PRIVILEGES for future migrations
4. Alembic migration trade-off: least-privilege app role lacks CREATE, so operators should use a separate migrator role for migrations

Documentation only — no runtime enforcement.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | SEC-FU-02 — Verify + pin DEMO_JWT_SECRET refusal | b4848816 | backend/tests/test_demo_credentials_guard.py |
| 2 | SEC-FU-09 — Add server_tokens off to nginx.conf | 85bbca7e | frontend/nginx.conf |
| 3 | SEC-FU-10 — Document least-privilege role in .env.example | 14d57df2 | .env.example |

## Verification Results

1. `pytest tests/test_demo_credentials_guard.py -x -v` — 7/7 PASS (includes SEC-FU-02 pin, both demo_mode values)
2. `grep -nE "^[[:space:]]*server_tokens[[:space:]]+off;" frontend/nginx.conf` — 1 hit at line 34
3. `grep -c "least-privilege" .env.example` — 1 hit
4. `grep -nE "DEMO_JWT_SECRET|demo-only-do-not-use-in-production-change-me" backend/app/core/config.py | grep -v "^#"` — 2 hits (constant definition + guard branch)

## Deviations from Plan

None — plan executed exactly as written. config.py verification confirmed Phase 1061 Plan 05 coverage was correct; no config.py changes were needed.

## Self-Check: PASSED

- `backend/tests/test_demo_credentials_guard.py` modified — confirmed via grep and pytest run
- `frontend/nginx.conf` modified — `server_tokens off;` at line 34 confirmed
- `.env.example` modified — "least-privilege" confirmed present
- Commits b4848816, 85bbca7e, 14d57df2 verified via git log
