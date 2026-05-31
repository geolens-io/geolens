# Phase 1157: Backend Export Access + Route Hygiene - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with audited fix shapes from REQUIREMENTS.md + STATE.md + `.planning/backlog/qa-260530-egress-gating.md` + `.planning/backlog/quick-260530-ezw-lowpri.md`

<domain>
## Phase Boundary

Three backend fixes (no new deps/migrations/features; existing files only):
- **EXP-01 (#121):** Anonymous users can export a published **public** dataset in every file format (gpkg/geojson/shp/csv). Today `export_dataset_endpoint` forces auth before any visibility check, so anon export of public data 401s.
- **EXP-02 (QZ-LP-02):** A regression test proves anon + non-owner export of **private/restricted/unpublished** datasets stays denied (401/403/404) after EXP-01.
- **API-01 (QZ-LP-03):** `GET /collections/{id}/items/` (trailing slash) resolves like the no-slash form instead of 404, via a dual-shape alias.

</domain>

<decisions>
## Implementation Decisions

### EXP-01 — vector export anon access (audited)
- Offender: `export_dataset_endpoint` (`backend/app/processing/export/router.py:47`) currently uses `require_permission("export")`, which forces authentication before any visibility check.
- Fix shape: **mirror the anonymous COG-download gate** (`download_cog` in `backend/app/modules/catalog/datasets/api/router_export.py:354`):
  - Use a `_resolve_download_user`-style resolution (`router_export.py:254`) — returns None for a valid no-sub download token / anonymous.
  - Branch on `user is None` → allow public+published via `check_dataset_access_or_anonymous` **plus a public-visibility defense-in-depth guard** (`router_export.py:385-407` is the reference).
  - Keep the `export` **capability** check ONLY on the authenticated path (anonymous public export needs no capability — matches OGC/tiles).

### API-01 — trailing-slash dual-shape alias (audited)
- Add `/collections/{id}/items/` (trailing slash) as a dual-shape alias resolving like the no-slash form, per the **Phase 1092 ROUTE-01 stacked-decorator pattern** (`redirect_slashes=False` at app level — `backend/app/api/main.py:443-469`). Register both shapes via stacked `@router.get` decorators (same pattern as `/api/collections/` and `/api/auth/login/`). Frontend uses the no-slash form today; this is a low-risk consistency fix.

### EXP-02 — regression test (audited)
- Prove anon AND non-owner export of private/restricted/unpublished datasets returns 401/403/404 after EXP-01.
- No draft/ready vector dataset exists in the dev DB — **seed or construct one in the test** (mirror the 1156 `_create_vector_dataset` factory shape in `backend/tests/test_vector_tile_auth.py` — visibility + record_status are settable).

</decisions>

<code_context>
## Existing Code Insights

### Files to change
- `backend/app/processing/export/router.py` (EXP-01 — `export_dataset_endpoint:47`)
- The OGC collections items router for API-01 (locate the `/collections/{id}/items` route; mirror the stacked-decorator dual-shape registration).
- New test file for EXP-02 (e.g. `backend/tests/test_export_access.py`).

### Reference implementation (copy this shape — COG download anon gate)
- `download_cog` (`backend/app/modules/catalog/datasets/api/router_export.py:354`) + `_resolve_download_user` (`:254`) + the public-visibility guard (`:385-407`).

### Canonical access contract — GOTCHA learned in Phase 1156 (apply here)
- **`check_dataset_access_or_anonymous` is NOT a method on the processing port.** A Phase 1156 attempt to call `port.check_dataset_access_or_anonymous(...)` was silently non-functional (AttributeError at runtime). Import it directly: `from app.modules.catalog.authorization import check_dataset_access_or_anonymous`.
- It returns **404** for a denied anonymous request (hides existence). For authenticated denials, `check_dataset_access` also raises 404. So EXP-02's "denied" assertion should accept the set **{401, 403, 404}** rather than pinning one code — `require_permission` raises 401/403 for the authenticated-no-capability path, and the anonymous/visibility gate raises 404.
- Contract: `can_access_dataset()` (`backend/app/platform/extensions/defaults.py:93`, anon branch `:109-110`) = `visibility=='public' AND record_status=='published'` for `user is None`.

### Route-hygiene precedent
- Phase 1092 ROUTE-01: `redirect_slashes=False` at app level; the two previously-leaking surfaces register both slash + no-slash shapes via stacked decorators. Vite dev-proxy rewrites residual `Location:` headers as defense in depth.

### Test-env recipe
- From `backend/`: `set -a && source ../.env.test && set +a` then `uv run pytest tests/test_export_access.py -v`. `.env.test` sets `POSTGRES_HOST=localhost` + `POSTGRES_PORT=5434`. db is up.

</code_context>

<specifics>
## Specific Ideas

- **EXP-01 success criteria:** anon GET export for public+published returns a real file body for gpkg/geojson/shp/csv; unpublished/private/restricted export stays denied.
- **EXP-02:** seed a draft/ready (unpublished) vector dataset + a private dataset; assert anon + non-owner export → denied (401/403/404); assert public+published export → allowed (mirror the over-gating guard pattern from 1156).
- **API-01:** `GET /collections/{id}/items/` returns the same result as `/collections/{id}/items` (not 404). Pin with a test hitting both shapes.
- GitHub issues: EXP-01 #121, API-01 + EXP-02 from `quick-260530-ezw-lowpri.md` (QZ-LP-02, QZ-LP-03).
- **Out of scope:** a per-deployment toggle to restrict anonymous public file export — explicit product decision, deferred (v1035 Out of Scope).

</specifics>

<deferred>
## Deferred Ideas

- Per-deployment policy toggle to restrict anonymous public **file export** — out of scope (product decision).

</deferred>
