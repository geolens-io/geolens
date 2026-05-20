# Phase 1062: MEDIUM severity remediation - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close 9 MEDIUM findings from `/sec-audit` 2026-05-19. None are merge-gate BLOCK, but together they close meaningful defense-in-depth gaps: embed-token framing CSP, ogr2ogr `-where` sqlglot validator, basemap api_key public-exposure docstring + rate limit, per-route rate limits to cap OpenAI embed cost, non-English FTS regconfig, input-length caps on search facets, JWT-in-localStorage ESLint guard + httpOnly migration plan, JWT revocation primitives, and password complexity validator.

**Requirements:** SEC-S08, SEC-S09, SEC-S10, SEC-S11, SEC-S12, SEC-S13, SEC-S14, SEC-S15, SEC-S16 (9 total)

**Source of truth:** `docs-internal/audits/sec-audit-20260519.md` §"Medium severity" (lines 363-410). Each REQ-ID maps to a Finding ID (S08-S16) section.

**Pre-drafted regression tests:** `e2e/sec-audit.spec.ts` (S08, S09, S10, S11, S13 specifically have test stubs). Plan 05 of Phase 1061 already extended this file with S06-S09 regression suite — verify what's already covered and don't duplicate.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, REQUIREMENTS.md acceptance criteria, codebase conventions, and Phase 1061 SUMMARYs as references.

### Key technical decisions (locked at planner time)

1. **SEC-S15 JWT revocation pattern:** Add `jti` (uuid4 hex) + `token_version` (integer FK to User row) claims at token issuance. Revocation = bump `User.token_version` → all prior JWTs fail validation. Add `User.token_version` column with Alembic migration (default 1). Verify both at access-token + refresh-token validation paths.

2. **SEC-S11 rate-limit approach:** Use existing `slowapi` infrastructure (already in deps per `frontend/src/lib/...` references). Per-IP + per-token caps configurable via `.env`. Apply to `/search/datasets/` and `/datasets/{id}/related/` first (OpenAI embedding cost cap); SEC-S10 basemap-proxy gets the same pattern.

3. **SEC-S12 non-English FTS:** Migration adds `idx_record_text_simple` GIN index using `simple` regconfig. Query path picks `simple` when locale != 'en'. Backward-compatible — existing `english`-regconfig query path stays for English.

4. **SEC-S14 ESLint guard:** New ESLint rule in `frontend/eslint.config.js` that detects `localStorage.setItem(*, ...)` calls where the first arg matches `/token|jwt|auth/i`. Document the httpOnly-cookie migration plan in `docs-internal/audits/security-lessons.md`.

5. **SEC-S16 password complexity:** Validator at `backend/app/modules/auth/dependencies.py` (or service module). Minimum 12 chars; configurable via `.env` (`PASSWORD_MIN_LENGTH`, `PASSWORD_REQUIRE_CLASSES`). Reject weak passwords with 422 + clear error message.

6. **Plan ordering:** Group by file surface to minimize cross-plan conflicts:
   - Plan 01: SEC-S15 + SEC-S16 (auth module — JWT + password)
   - Plan 02: SEC-S10 + SEC-S11 (rate limiting — slowapi wiring)
   - Plan 03: SEC-S12 + SEC-S13 (search facets — Postgres FTS + input caps)
   - Plan 04: SEC-S09 (ogr2ogr -where validator — processing module)
   - Plan 05: SEC-S08 (embed framing CSP — frontend + backend headers)
   - Plan 06: SEC-S14 (ESLint guard — frontend lint config + docs)

### Test strategy
- Each plan adds backend pytest tests for its MEDIUM finding.
- `e2e/sec-audit.spec.ts` S08, S09, S10, S11, S13 pre-drafted — plans should USE these.
- Migration tests (SEC-S15, SEC-S12): run `alembic upgrade head` + `alembic downgrade -1` cycle.
- Rate-limit tests: assert 429 returned after threshold (configurable so tests can set low threshold).

</decisions>

<code_context>
## Existing Code Insights

- **slowapi:** Likely already wired — check `backend/app/main.py` for `Limiter` instantiation.
- **FTS query path:** `backend/app/modules/search/` and `backend/app/standards/ogc/` use Postgres FTS via `to_tsvector` + `plainto_tsquery`. The `english` regconfig is the current default.
- **JWT issuance:** `backend/app/modules/auth/jwt.py` (or similar) — find via `grep -r "jwt.encode\|jwt.decode"`.
- **Password registration:** `backend/app/modules/auth/dependencies.py` or `service.py`. Look for `hash_password` + `verify_password`.
- **ESLint config:** `frontend/eslint.config.js`. Existing rules in flat-config format.
- **Embed CSP:** `backend/app/middleware/` or main.py — search for `Content-Security-Policy`.
- **ogr2ogr -where:** `backend/app/processing/ingest/ogr.py` builds the `-where` arg. User input source is service URL adapter input (e.g., WFS `cql_filter`).

</code_context>

<specifics>
## Specific Ideas

**SEC-S08 (embed framing CSP):**
- Audit `backend/app/main.py` CSP middleware for `frame-ancestors` directive.
- Should match the configured embed allowlist (per-share-token or per-tenant).
- Test: shared embed iframe rejects load from non-allowlisted domain.

**SEC-S09 (ogr2ogr -where sqlglot validator):**
- New helper in `backend/app/processing/ingest/where_validator.py` or similar.
- Parse `-where` clause with sqlglot; reject if AST contains DDL (CREATE/DROP), UNION, SELECT, semicolon (multi-statement), or function calls not on a whitelist.
- Acceptance: malicious `-where "1=1; DROP TABLE users; --"` rejected with 422 at API boundary.

**SEC-S10 (basemap api_key + rate limit):**
- Docstring on basemap proxy endpoint explaining `api_key` is public-facing (not a secret — rotation guidance).
- Rate limit per IP on `/basemap-proxy` to cap abuse.

**SEC-S11 (per-route rate limit):**
- Apply slowapi limit decorator on `/search/datasets/` (e.g., 60/min per IP).
- Same on `/datasets/{id}/related/`.
- Caps OpenAI embedding cost.

**SEC-S12 (simple-regconfig GIN):**
- Migration: add `idx_record_text_simple` using `to_tsvector('simple', title || ' ' || summary || ...)`
- Query: pick regconfig based on locale.

**SEC-S13 (search facets max_length):**
- Add `max_length=1000` to `q` query param on `/search/facets/?q=`.
- Acceptance: 1001-char payload → 422.

**SEC-S14 (JWT-in-localStorage guard):**
- ESLint custom rule or `no-restricted-syntax` matching `localStorage.setItem(/(token|jwt|auth)/, ...)`.
- httpOnly-cookie migration plan documented in security-lessons.md (defer implementation — this just guards regression).

**SEC-S15 (JWT jti + token_version):**
- Alembic migration: add `users.token_version INTEGER NOT NULL DEFAULT 1`.
- Issuance: include `jti=uuid4().hex` + `token_version=user.token_version` in claims.
- Validation: reject if `token_version` in JWT < User's current `token_version`.
- Revocation endpoint: `POST /admin/users/{id}/revoke-tokens/` → increment `token_version`.

**SEC-S16 (password complexity):**
- Validator at registration + change-password.
- Minimum 12 chars (configurable).
- Mix of letter classes (lower, upper, digit, symbol) — at least 3 of 4 by default.
- Configurable per `.env`.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

Related but out of scope for Phase 1062:
- LOW follow-ups (SEC-FU-01..FU-10) → Phase 1063
- Close gate (SEC-CTRL-01) → Phase 1064
- httpOnly-cookie migration (alluded to in SEC-S14) → tracked in security-lessons.md, not in v1014 scope

</deferred>
