# Phase 1061: HIGH severity remediation + AGENTS.md guardrail - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close 7 HIGH findings from `/sec-audit` 2026-05-19 (merge gate currently **BLOCK**) and pin the visibility-filter coverage pattern in AGENTS.md to prevent regression. Five of the seven HIGHs cluster on the same architectural pattern — new Record-derived endpoints reaching for `require_permission()` (role-level) and skipping `check_dataset_access()` / `apply_visibility_filter()` (resource-level). One SSRF redirect-bypass widens the blast radius beyond authenticated editors. Two configuration HIGHs around demo/MinIO credentials.

**Requirements:** SEC-S01, SEC-S02, SEC-S03, SEC-S04, SEC-S05, SEC-S06, SEC-S07, SEC-GUARD-01

**Source of truth:** `docs-internal/audits/sec-audit-20260519.md` (561 lines, 41KB). Each REQ-ID maps to a Finding ID in §"Finding details" (S01-S07) or to the headline pattern in §"Executive summary".

**Pre-drafted regression tests:** `e2e/sec-audit.spec.ts` (18 tests, env-var-gated).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, REQUIREMENTS.md acceptance criteria, and codebase conventions to guide decisions.

### Key technical decisions (locked at planner time)

1. **Visibility-filter coverage pattern (S01, S02, S03, S05):** The OGC API router (`backend/app/standards/ogc/router.py`) is the reference implementation — apply the same `user`/`user_roles` threading + `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` pattern. For mutation handlers (S02, S03), `check_dataset_access(dataset, user, user_roles, action="write")` AFTER `get_dataset()` is the correct gate; for read handlers (S05), `check_dataset_access_or_anonymous` allows public access while still filtering private/grant-only records.

2. **SSRF (S04) approach:** Custom `make_safe_client()` factory in `backend/app/modules/catalog/sources/router.py` (or shared helper module). Use httpx `event_hooks={"response": [_revalidate_redirect]}` with a per-hop SSRF allowlist check. For ogr2ogr subprocess calls, set `GDAL_HTTP_FOLLOWLOCATION=NO` to disable redirect-following entirely (safer than per-hop validation when GDAL is the consumer).

3. **Demo credentials (S06) approach:** Rename committed `.env.demo` → `.env.demo.example` (no real defaults). Add `scripts/init-demo-env.sh` that generates per-deploy random credentials. Extend the existing `validate_demo_credentials_guard` in backend startup to refuse known literal defaults (e.g., `JWT_SECRET_KEY=demo-only-do-not-use-in-production-change-me`).

4. **MinIO defaults (S07) approach:** Drop `:-minioadmin` defaults in `docker-compose.yml`. Use `${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}` shell expansion for fail-closed behavior.

5. **AGENTS.md guardrail (SEC-GUARD-01):** Add the visibility-filter coverage rule directly to AGENTS.md as a Pre-Commit Checklist item. Optional pre-commit grep guardrail in `.pre-commit-config.yaml` if low-noise; otherwise document as manual review.

### Test strategy
- `e2e/sec-audit.spec.ts` is pre-drafted with 18 tests pinning S01–S13. Each plan should run the relevant subset locally during development.
- Backend pytest must add unit tests for new helpers (`make_safe_client`, `_revalidate_redirect`, extended `validate_demo_credentials_guard`).
- Frontend unit tests not applicable (this phase is backend + config + docs).

</decisions>

<code_context>
## Existing Code Insights

The codebase already has the building blocks:

- **`check_dataset_access(dataset, user, user_roles, action)`** — at `backend/app/modules/catalog/authorization.py` (relocated in v13.1). Owner + grant + admin check.
- **`check_dataset_access_or_anonymous`** — same module, allows public access while filtering private/grant-only.
- **`apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)`** — same module. Returns a SQLAlchemy `Select` with the visibility predicate appended.
- **`require_permission()`** — `backend/app/modules/auth/dependencies.py`. ROLE-level check only (not resource-level). The audit's headline finding: code under audit was using this WHERE it should have called `check_dataset_access`.
- **OGC API router** at `backend/app/standards/ogc/router.py` is the visibility-filter-correct reference. Read this before touching STAC router.
- **SSRF allowlist** — existing `_assert_safe_url()` helper exists in `backend/app/modules/catalog/sources/router.py`. Currently invoked at request entry but not per-redirect-hop.
- **Pre-existing pytest fixture coverage** — `backend/tests/conftest.py` has `editor_user`, `editor_user_b`, `private_record_owned_by_editor` fixtures useful for IDOR tests.

</code_context>

<specifics>
## Specific Ideas

Specific implementation tasks per requirement:

**SEC-S01 (STAC visibility filter):**
- Thread `user` and `user_roles` from `Depends(get_current_user_or_anonymous)` + `Depends(get_user_roles)` into every read route in `backend/app/standards/stac/router.py:54-822` (collections list, search, item-detail, etc.).
- Apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying Record queries.

**SEC-S02 (dataset metadata IDOR):**
- `backend/app/modules/catalog/datasets/api/router.py:263-426` — 3 mutation handlers (update_dataset, delete_dataset, restore_dataset — verify against current code).
- Add `check_dataset_access(dataset, user, user_roles, action="write")` after `get_dataset()` call. Returns 403 on access denial.

**SEC-S03 (column DDL IDOR):**
- `backend/app/modules/catalog/layers/router.py:94-301` — 4 column-DDL handlers (add_column, drop_column, rename_column, modify_column-type — verify against current code).
- Same `check_dataset_access` pattern as S02.

**SEC-S04 (SSRF redirect-bypass):**
- New `make_safe_client()` factory in `backend/app/modules/catalog/sources/router.py` (or shared module).
- httpx client with `event_hooks={"response": [_revalidate_redirect]}` — each redirect target gets re-validated against the SSRF allowlist.
- Set `GDAL_HTTP_FOLLOWLOCATION=NO` env var for ogr2ogr subprocess calls in `backend/app/processing/ingest/ogr.py`.

**SEC-S05 (related-datasets IDOR):**
- `backend/app/modules/catalog/datasets/api/router_data.py:56-65` — `get_related_datasets` endpoint.
- Add `check_dataset_access_or_anonymous(dataset, user, user_roles)` BEFORE the related lookup. Apply visibility filter to the related query.

**SEC-S06 (demo credentials):**
- Rename `.env.demo` → `.env.demo.example`. Make sure no real secrets land in the example.
- Add `scripts/init-demo-env.sh` that:
  - Generates random `JWT_SECRET_KEY` (>=32 bytes urandom base64),
  - Generates random `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`,
  - Writes the result to `.env.demo` (gitignored).
- Extend `validate_demo_credentials_guard` (backend startup) to refuse known literal defaults from `.env.demo.example`.

**SEC-S07 (MinIO defaults):**
- `docker-compose.yml:507-508,536` — drop `:-minioadmin` shell defaults.
- Use `${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}` for fail-closed behavior.

**SEC-GUARD-01 (AGENTS.md guardrail):**
- AGENTS.md gets a "Visibility-filter coverage" section under the Pre-Commit Checklist.
- Optional: `.pre-commit-config.yaml` grep hook that flags new routes touching `Record.id` without an adjacent `check_dataset_access`/`apply_visibility_filter` call. Evaluate noise level first; ship only if low-false-positive.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

Related but out of scope for Phase 1061:
- MEDIUM follow-ups (S08-S16) → Phase 1062
- LOW follow-ups (SEC-FU-01..FU-10) → Phase 1063
- Close gate (SEC-CTRL-01) → Phase 1064

</deferred>
