# Phase 1156: Vector-Tile Egress Authorization - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with audited fix shape from REQUIREMENTS.md + STATE.md + `.planning/backlog/qa-260530-egress-gating.md`

<domain>
## Phase Boundary

Close SEC-01: a real anonymous data leak. The vector-tile authorization path checks dataset **visibility only** and never consults **record_status**, so a `visibility=public` but **unpublished** (draft/ready/internal) dataset leaks its MVT feature data + a valid HMAC tile token to any anonymous caller (live-proven: 200 + 1842 bytes of MVT served to anon).

This phase makes the vector path enforce the same contract the raster path already enforces: anonymous access requires `visibility=='public' AND record_status=='published'`. Backend-only; fixes to existing files; no new deps/migrations/features.

</domain>

<decisions>
## Implementation Decisions

### Fix shape (audited — mirror the raster path)
- The **raster** path is the correct reference model: `backend/app/processing/tiles/router.py:438,467` already gates on published status for anonymous callers. Mirror its branch structure across the four/five vector entry points.
- Route anonymous callers through the **canonical status-aware contract**, NOT a visibility-only check:
  - `can_access_dataset()` (`backend/app/platform/extensions/defaults.py:93`) returns `visibility=='public' AND record_status=='published'` for `user is None` (`:109-110`).
  - Query-level equivalent: `filter_visible()` anon branch (`backend/app/platform/extensions/defaults.py:61-65`).
  - Wrappers: `check_dataset_access_or_anonymous()` / `check_dataset_access()` (`backend/app/modules/catalog/authorization.py:75,100`).
- Use whichever of these (or an inline status-aware 3-branch check) keeps the diff smallest and consistent with the raster path. Owner / admin / embed-token paths must remain unchanged (no over-gating).

### Entry points to fix (all five)
1. `_authorize_vector_tile_request` (`tiles/router.py:1053`) — the `.pbf` data path.
2. `_DatasetMeta` / `_resolve_dataset_meta` (`tiles/router.py:1015`) — must **carry `record_status`** through so callers can gate on it (today it likely only carries visibility/owner).
3. `get_tile_token` (`tiles/router.py:866`) — single HMAC token minting.
4. `get_tile_tokens_batch` (`tiles/router.py:939`) — batch token minting.
5. `cluster_tile_endpoint` (`tiles/router.py:1130`) — clustered point tiles inherit the same denial.

### Over-gating guardrail
- A `public` + `published` vector dataset must STILL serve tiles + tokens to anonymous callers. Do not break the legitimate public-published anonymous path.

</decisions>

<code_context>
## Existing Code Insights

### Reference implementation (raster — copy this shape)
- `backend/app/processing/tiles/router.py:438,467` — raster anonymous gate already requires published.

### Files to change
- `backend/app/processing/tiles/router.py` — entry points at lines ~866, ~939, ~1015, ~1053, ~1130.

### Canonical access contract (do not reinvent)
- `backend/app/platform/extensions/defaults.py:61-65` (query filter), `:93,109-110` (`can_access_dataset`).
- `backend/app/modules/catalog/authorization.py:75` (`check_dataset_access_or_anonymous`), `:100` (`check_dataset_access`).

### Test infra
- Backend tests need: `set -a && source ../.env.test && set +a` from `backend/` before `uv run pytest` (else `InvalidCatalogNameError`). `.env.test` sets `POSTGRES_HOST=localhost` + `POSTGRES_PORT=5434`.
- Focused run target: tiles router tests under `backend/tests/`.

</code_context>

<specifics>
## Specific Ideas

- **Regression test (success criterion 5):** anonymous tile-token request + anonymous `.pbf` request on a **public-but-unpublished** vector dataset must return 401/404 (today both 200; the `.pbf` returns 1842 bytes of feature data). Also assert the **positive** case: public+published still serves to anon (guards against over-gating).
- **Clustered tiles:** include `cluster_tile_endpoint` in both the fix and the test matrix.
- Full root-cause analysis with line refs: `.planning/backlog/qa-260530-egress-gating.md`. GitHub issue #124.
- Success criteria (must all be TRUE):
  1. Anon `.pbf` for public-unpublished → 401/404.
  2. Anon single + batch token for public-unpublished → 401/404 (no HMAC minted).
  3. `cluster_tile_endpoint` inherits status-aware denial.
  4. public+published still serves to anon; owner/admin/embed-token unchanged.
  5. Regression test pins the denial.

</specifics>

<deferred>
## Deferred Ideas

- Per-deployment toggle to restrict anonymous **file export** of public data — out of scope (product decision; tracked in v1035 Out of Scope).

</deferred>
