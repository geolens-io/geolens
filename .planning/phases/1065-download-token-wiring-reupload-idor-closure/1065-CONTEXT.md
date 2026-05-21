# Phase 1065: Download Token Wiring + Reupload IDOR Closure - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous mode — seed + actual code paths confirmed)

<domain>
## Phase Boundary

This phase delivers three security/UX fixes that all touch the catalog dataset authorization perimeter and share the `check_dataset_access` pattern:

1. **IA-P0-01 — Download COG token-mint flow**: Currently broken in production. Frontend `downloadCog()` (`frontend/src/api/datasets.ts:105-112`) passes the session JWT as `?token=...`, but backend `router_export.py:185-201` requires a `typ='download'` JWT (the existing `create_download_token` helper at `backend/app/modules/auth/service.py:78-111`). Phase wires the missing endpoint and updates the frontend to mint→open.
2. **REUPLOAD-IDOR-01 — Reupload resource-level authorization**: All 6 handlers in `backend/app/modules/catalog/datasets/api/router_reupload.py` use only `require_permission("edit_metadata")` (role-level). Add `check_dataset_access` (write-mode + ownership) to each, mirroring the v1014 SEC-S02 pattern. Delete the pre-commit `router_reupload.py` exclusion at `.pre-commit-config.yaml:76-79` at the end.
3. **IA-P1-02 — Reupload record-type compatibility guard**: `reupload_service_preview` is missing the `_assert_compatible_record_type` call that the multipart and presigned-URL paths already enforce. Add the call at function entry.

Out of phase: anything touching ingest entry-point validation (Phase 1066), heartbeat (1067), service-URL hardening (1068), export (1069), or hygiene closeout (1070).

</domain>

<decisions>
## Implementation Decisions

### Download Token Endpoint (IA-P0-01)

- **Endpoint shape:** `POST /api/auth/download-token/{dataset_id}` returns `{ "token": "<jwt>", "expires_in": 120 }`. POST not GET because it mutates security state (issues a credential).
- **Authorization:** Resource-level check via existing `check_dataset_access_or_anonymous` (read-mode). A user who can VIEW the dataset can download it — symmetry with the existing COG download view path. Anonymous public-dataset downloads remain allowed via the same anonymous read path used elsewhere.
- **TTL:** 120 seconds — already enforced as a cap in `create_download_token` (`auth/service.py:96`). Frontend mints just-in-time; no caching.
- **Rate limit:** Apply `Depends(rate_limit(...))` at 60/min per user to deter token-farming. Mirrors the v1014 SEC-S10/S11 per-route limits.
- **Frontend change:** `downloadCog()` becomes async: mint via `POST /auth/download-token/{id}` (uses session JWT in `Authorization` header via existing `apiFetch`), then open `${API_BASE}/datasets/${id}/download/cog?token=${downloadToken}` in a new tab. No localStorage caching of the download token.
- **Regression test:** Playwright spec that mocks the network — assert (a) the first request hits `/auth/download-token/`, (b) the second request to `/download/cog` carries the minted token (NOT the session JWT). Pin the failure mode that's currently in production.

### Reupload IDOR Closure (REUPLOAD-IDOR-01)

- **Pattern:** Mirror v1014 SEC-S02 — every `router_reupload.py` handler that takes a `dataset_id` (path or body) calls `await check_dataset_access(db, dataset_id, user, write=True)` immediately after the existing `require_permission` dep. Non-owner editors get a `404` (consistent with v1014's choice to not reveal dataset existence) rather than `403`. We'll match whatever shape `check_dataset_access` already returns.
- **Coverage:** 6 handlers — exact list to be enumerated during plan-phase by grepping `require_permission("edit_metadata")` against the file. Each is one ~3-line insertion.
- **Pre-commit exclusion deletion:** `.pre-commit-config.yaml:76-79` `router_reupload.py` exclusion is deleted in the same plan that closes the IDOR — fails closed if any handler is missed.
- **Regression test:** parameterized pytest hitting each of the 6 handlers with a non-owner editor; assert 404 from each.
- **Scope discipline:** This phase does NOT redesign `router_reupload.py` — just adds the missing check. Wholesale redesign is explicitly out of scope per REQUIREMENTS.md.

### Reupload Record-Type Guard (IA-P1-02)

- **Surface:** Add `_assert_compatible_record_type(record, requested_kind)` as the first call in `reupload_service_preview` after the existing access check. Mirror exactly the multipart path at `:127` and presigned path at `:521`.
- **Test:** unit test where a vector record is reuploaded as raster — assert 4xx (specific status mirrors existing helper's raise behavior, likely 400 or 409).

### Claude's Discretion

- Exact handler-by-handler diff in `router_reupload.py` (the seed enumerates 6 handlers but doesn't name them — plan-phase enumerates).
- Test file organization: prefer co-locating new tests with the touched modules (`backend/tests/modules/auth/...`, `backend/tests/modules/catalog/datasets/api/...`).
- Frontend toast/error-state copy on download-token mint failure (likely: "Could not start COG download — try again" matching existing patterns).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `backend/app/modules/auth/service.py:78-111` — `create_download_token` helper already exists. The endpoint to expose it is the only missing piece for IA-P0-01.
- `backend/app/modules/catalog/authorization.py` — `check_dataset_access`, `check_dataset_access_or_anonymous`, `apply_visibility_filter`, `get_user_roles` — the canonical resource-level authorization toolkit established in v1014.
- `backend/app/modules/catalog/datasets/api/router_export.py:185-201` — existing `download_cog` endpoint that validates `typ='download'` JWT. Reference for the JWT decode/validation shape.
- v1014 SEC-S02 pattern: every metadata-mutation handler gates on `check_dataset_access` AFTER `require_permission`. Apply identically to reupload.
- Pre-commit hook `visibility-filter-coverage` (`.pre-commit-config.yaml`) — already scans for unguarded handlers. The `router_reupload.py` exclusion is what we're deleting.

### Established Patterns

- **Auth router shape:** `backend/app/modules/auth/router.py` — `POST` endpoints with FastAPI router, Pydantic response models, structlog usage.
- **Rate limiting:** `Depends(rate_limit(...))` decorator pattern from v1014 SEC-S10/S11.
- **`apiFetch` JWT auto-injection:** `frontend/src/api/client.ts` — handles Bearer token automatically; new `mintDownloadToken(id)` follows the same pattern.
- **Playwright network mocking:** existing patterns under `frontend/e2e/`.

### Integration Points

- New backend route at `backend/app/modules/auth/router.py` registered to the existing auth router.
- New frontend helper `mintDownloadToken(id)` in `frontend/src/api/datasets.ts` (same file as `downloadCog`).
- Updated `downloadCog` becomes `async` — confirm callers don't break (likely just dataset-detail page).
- Existing OpenAPI snapshot will need regeneration (`make openapi`) after the new endpoint lands; frontend SDK regeneration (`npm run fetch-openapi` in sibling docs repo) is out of phase scope per `project_openapi_dual_snapshot_refresh_order.md`.

</code_context>

<specifics>
## Specific Ideas

- **Frontend `downloadCog` change is the smaller half** — once the backend endpoint exists, it's a 6-line frontend tweak. Land backend + tests first, then frontend.
- **Pre-commit exclusion deletion is load-bearing** — leaving it would silently shield future regressions. Plan-phase must include the deletion in the same commit chain that closes the 6 handlers.
- **404 vs 403 from `check_dataset_access`** — match whatever the helper already returns. v1014 SEC-S02 chose 404 for IDOR-flavored cases. The regression tests assert the helper's actual return, not a guess.

</specifics>

<deferred>
## Deferred Ideas

- Switch the download token from `?token=` to a short-lived cookie (referenced in v1014 SEC-S14 ADR but explicitly httpOnly migration is out of scope here).
- Refactor `router_reupload.py` into smaller handlers — explicitly excluded by REQUIREMENTS.md Out-of-Scope.
- Wider reupload UX redesign — separate future phase.

</deferred>
