---
phase: 1073-audit-remediation
plan: 4
subsystem: backend
tags: [titiler, ssrf, refactor, security, observability, http-client]

# Dependency graph
requires:
  - phase: 1072-audit
    provides: INGEST-AUDIT-2026-05-21 (P2-01 duplicate Titiler URL construction) + SECURITY-AUDIT-2026-05-21 (SEC-OBSV-01 _titiler_client follow_redirects + SEC-OBSV-02 _fetch_cog_info dual-gate)
provides:
  - "Single source of truth for Titiler COG URL construction: backend/app/platform/storage/titiler_url.py"
  - "build_titiler_cog_url(endpoint, *, query, raw_query_suffix) helper with urllib.parse.urlencode for caller-supplied params + raw passthrough for pre-built render-params (repeated bidx)"
  - "_TITILER_BASE_URL module constant — one-line future env-driven override seam"
  - "SEC-OBSV-01 docstring pinned at tiles/router.py::_titiler_client: internal-only stance + make_safe_client migration trigger"
  - "SEC-OBSV-02 docstring pinned at stac_router.py::_fetch_cog_info: caller-side validate_url_for_ssrf + Titiler CPL_VSIL_CURL_ALLOWED_EXTENSIONS dual-gate enumeration"
  - "Structural regression test: every caller imports build_titiler_cog_url AND zero literal http://titiler:8000 strings survive in non-comment lines"
affects: [1073-05 (final close-gate roll-up), future Titiler-exposure changes, future _fetch_cog_info caller additions]

# Tech tracking
tech-stack:
  added: []  # no new deps; urllib.parse.urlencode is stdlib
  patterns:
    - "Single-helper URL builder for cross-module URL construction (consolidate 3 inline f-strings -> 1 helper + 2 callers)"
    - "raw_query_suffix passthrough alongside urlencoded query dict — supports repeated query keys (bidx=1&bidx=2) that urlencode would dedupe"
    - "SEC-OBSV docstring contracts at the const/function site enumerating both the today-is-safe rationale and the future-migration trigger — greppable from any audit"
    - "Structural pytest pin that reads source files at import-time and asserts (a) the helper is imported AND (b) no literal hostname survives in non-comment lines — prevents silent re-inlining"

key-files:
  created:
    - backend/app/platform/storage/titiler_url.py
    - backend/tests/test_titiler_url_helper.py
  modified:
    - backend/app/processing/tiles/router.py
    - backend/app/modules/catalog/sources/stac_router.py

key-decisions:
  - "Module name titiler_url.py (not cog_url.py): the URL targets the Titiler service, and the asset_uri ALSO appears in router_export.py (RedirectResponse) which is a separate concern. Conflating both under cog_url.py would mislead. Naming choice documented at the top of the new module."
  - "raw_query_suffix kwarg accepts a leading `?` or `&` and strips it (lstrip('?&')) — caller never produces `??bidx=1` even if they pre-mark the fragment. Test 5 pins this."
  - "Approximate comment-stripping in structural pin (only `#` lines, no `\"\"\"docstring\"\"\"` stripping): sufficient because the new SEC-OBSV-01/02 docstrings reference 'Titiler' in prose but never the literal `http://titiler:8000` host string. Verified by static read before committing the test."
  - "params= kwarg dropped at stac_router.py call sites: helper bakes URL-encoded query into the URL string. httpx accepts both shapes — the audit P2-01 wants ONE URL-construction surface (the helper), not a mix of helper-built URLs and httpx-built params."
  - "Bit-equivalence: caller-supplied URL is now `https%3A%2F%2F...` (urlencoded) instead of the prior `https://...` (raw). Titiler accepts both forms; behavior preserved at the receiving end. 14/14 test_raster_tiles.py + 45/45 STAC test suite pass unchanged."

patterns-established:
  - "Single-helper URL builder pattern: when N>=3 modules build the same internal URL via separate f-strings, the audit-correct refactor is one helper module + N callers."
  - "SEC-OBSV docstring contract: pin defense-in-depth assumptions at the construction site, naming the audit ID (e.g. SEC-OBSV-01), the today-is-safe condition, AND the future-migration trigger. Future auditors grep the ID."
  - "Structural regression pin: import-time source scan that asserts both the positive (import exists) and the negative (literal absent in non-comment lines) — both must hold or test fails."

requirements-completed: [REMED-04]

# Metrics
duration: 5min
completed: 2026-05-21
---

# Phase 1073 Plan 04: Titiler COG URL Helper Consolidation Summary

**Single Titiler COG URL helper (backend/app/platform/storage/titiler_url.py) consumed by 3 call sites (tiles/router.py:343, stac_router.py:55, stac_router.py:69); SEC-OBSV-01 (_titiler_client follow_redirects internal-only stance) + SEC-OBSV-02 (_fetch_cog_info dual-gate enumeration) docstrings pinned at their respective construction sites.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-21T14:54:56Z
- **Completed:** 2026-05-21T14:59:45Z
- **Tasks:** 5/5 (4 with code changes + 1 verification-only sweep)
- **Files modified:** 4 (2 created, 2 edited)

## Accomplishments

- `build_titiler_cog_url(endpoint, *, query, raw_query_suffix)` helper centralizes Titiler URL construction with `urllib.parse.urlencode` for caller-supplied params and `raw_query_suffix` passthrough for pre-built render-params (repeated `bidx` keys).
- `_TITILER_BASE_URL` module constant is a one-line seam for a future env-driven override.
- Three inlined `http://titiler:8000/cog/...` f-string sites consolidated into a single helper consumed by 3 callers.
- SEC-OBSV-01 docstring pinned at `_titiler_client`: internal-only rationale + `make_safe_client` migration trigger if Titiler is ever exposed externally OR user-controlled URLs reach this client.
- SEC-OBSV-02 docstring pinned at `_fetch_cog_info`: dual-gate enumeration (caller-side `validate_url_for_ssrf` + Titiler-side `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`).
- 8/8 helper tests (6 helper-shape + 2 structural-pin) + 14/14 test_raster_tiles.py + 45/45 STAC test suite all green.

## Task Commits

Each task was committed atomically; TDD tasks have separate RED and GREEN commits:

1. **Task 1 RED: failing helper tests** - `8cb818d6` (test)
2. **Task 1 GREEN: build_titiler_cog_url helper** - `afa5b320` (feat)
3. **Task 2: route tiles/router + SEC-OBSV-01 docstring** - `9e1cd403` (feat)
4. **Task 3: route stac_router + SEC-OBSV-02 docstring** - `c6f69498` (feat)
5. **Task 4: structural regression pins** - `d4968e3b` (test)
6. **Task 5: touched-area sweep** - verification-only, no commit (22/22 helper + raster pass)

**Plan metadata commit:** added separately for SUMMARY.md (`-f` because `.planning/` is gitignored).

## Files Created/Modified

- `backend/app/platform/storage/titiler_url.py` (created, 61 LOC) — single source of truth for Titiler COG URL construction. `build_titiler_cog_url(endpoint, *, query, raw_query_suffix)` + `_TITILER_BASE_URL` constant.
- `backend/tests/test_titiler_url_helper.py` (created, ~128 LOC) — 8 tests: 6 helper-shape (bare endpoint / encoded query / raw passthrough / combined / leading-?-or-&-strip / nested-slash tiles path) + 2 structural-pin (each caller imports the helper AND has zero literal `http://titiler:8000` in non-comment lines).
- `backend/app/processing/tiles/router.py` (modified) — imported the helper; replaced the three-branch f-string at line 343-347 with one helper call; added the SEC-OBSV-01 block above `_titiler_client`.
- `backend/app/modules/catalog/sources/stac_router.py` (modified) — imported the helper; replaced both `client.get("http://titiler:8000/cog/...", params={"url": url})` shapes with `client.get(build_titiler_cog_url(..., query={"url": url}))`; extended the `_fetch_cog_info` docstring with the SEC-OBSV-02 dual-gate enumeration.

## Decisions Made

- **Module name `titiler_url.py`** (not `cog_url.py`): the URL targets the Titiler *service*, while `asset_uri` also flows through `router_export.py` RedirectResponse as a separate concern. The CONTEXT.md "Claude's Discretion" line gave latitude here; named the module after the service that hosts the URLs, not the path prefix.
- **`raw_query_suffix` accepts leading `?` or `&`**: `lstrip("?&")` ensures callers never produce `??bidx=1` even if they pre-mark the fragment. Test 5 pins this.
- **`params=` kwarg dropped at the stac_router call sites**: P2-01's intent is ONE URL-construction surface. The helper produces the full URL string with the query baked in via `urlencode`; httpx accepts that shape (bit-equivalent at the wire for Titiler, which decodes `%3A`/`%2F` back to `:`/`/`).
- **Approximate `#`-only comment stripping in the structural pin**: sufficient because the new SEC-OBSV docstrings reference "Titiler" in prose but never the literal `http://titiler:8000` host string (verified by static read before committing the test).

## Deviations from Plan

None — plan executed exactly as written.

The plan's `<behavior>` block at Task 2 said "bit-for-bit identical to the previous f-string output". Strictly, the helper output is `?url=https%3A%2F%2F...` while the previous f-string was `?url=https://...`. This is the documented behavior of `urlencode` AND it is what Task 1's test 2 asserts — so the plan internally specified the encoded shape. Titiler decodes both shapes identically (RFC 3986 reserved char encoding is parser-equivalent). 14/14 raster tile tests + 45/45 STAC tests pass without modification, confirming wire-level behavior is preserved. No deviation needed.

## Issues Encountered

- **pytest can't run inside the api container** (no pytest installed at `/usr/local/bin/python`). Tests must run from host with `POSTGRES_HOST=localhost POSTGRES_PORT=5434` (matching docker-compose's `127.0.0.1:5434->5432/tcp` mapping for the `db` service). Followed the host-side test command pattern from the Makefile's `cli-test` target. Not a regression — same pattern used by the existing CLI test target.

## User Setup Required

None — internal refactor + docstring pins only; no env, schema, or external service changes.

## Next Phase Readiness

- REMED-04 closed: helper exists, both callers consume it, both SEC-OBSV docstrings are pinned, structural regression test guards re-inlining.
- Phase 1073's close-gate plan (1073-05 or equivalent) can roll up REMED-04 alongside any other Phase 1073 plans' deliverables.
- Future Titiler-exposure changes (e.g. moving Titiler behind a public route) MUST grep `SEC-OBSV-01` in `tiles/router.py` and reroute `_titiler_client` through `make_safe_client` before the change ships.
- Future callers of `_fetch_cog_info` MUST grep `SEC-OBSV-02` in `stac_router.py` and ensure caller-side `validate_url_for_ssrf` is in place before the call.

## Self-Check

Verification of every claim above:

**Files created/modified exist:**
- `backend/app/platform/storage/titiler_url.py`: FOUND
- `backend/tests/test_titiler_url_helper.py`: FOUND
- `backend/app/processing/tiles/router.py` (modified): FOUND
- `backend/app/modules/catalog/sources/stac_router.py` (modified): FOUND

**Task commits exist in git log:**
- `8cb818d6` (Task 1 RED): FOUND
- `afa5b320` (Task 1 GREEN): FOUND
- `9e1cd403` (Task 2): FOUND
- `c6f69498` (Task 3): FOUND
- `d4968e3b` (Task 4): FOUND

**Done-criteria grep counts:**
- `http://titiler:8000` in `tiles/router.py` + `stac_router.py`: 0 (target: 0)
- `SEC-OBSV-01` in `tiles/router.py`: 1 (target: >= 1)
- `SEC-OBSV-02` in `stac_router.py`: 1 (target: >= 1)
- `build_titiler_cog_url` in `tiles/router.py`: 3 (import + comment + call) (target: >= 1)
- `build_titiler_cog_url` in `stac_router.py`: 3 (import + 2 call sites) (target: >= 2)

**Test suites green:**
- `tests/test_titiler_url_helper.py`: 8/8 pass
- `tests/test_raster_tiles.py`: 14/14 pass
- `tests/test_stac_import.py tests/test_stac_api.py tests/test_stac_visibility.py`: 45/45 pass

## Self-Check: PASSED

---
*Phase: 1073-audit-remediation*
*Completed: 2026-05-21*
