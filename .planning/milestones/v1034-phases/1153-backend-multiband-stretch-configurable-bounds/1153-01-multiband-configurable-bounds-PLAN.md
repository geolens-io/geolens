---
phase: 1153-backend-multiband-stretch-configurable-bounds
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/processing/tiles/router.py
  - backend/tests/test_raster_colormap_proxy.py
autonomous: true
requirements:
  - RASTER-STRETCH-03
  - SPIKE-01
  - RASTER-STRETCH-UI-01

must_haves:
  truths:
    - "A 3-band raster with stretch=percentile produces a Titiler URL containing exactly 3 rescale= fragments"
    - "pmin/pmax/sigma query params on raster_tile_proxy override the fixed 2/98 percentile + 2.0 sigma"
    - "Two requests for the same asset with different pmin/pmax produce distinct _band_stats_cache entries and distinct rescale= values"
    - "Invalid bounds (pmin>=pmax, pmin<0, pmax>100, sigma<=0) return HTTP 422 before Titiler is called"
    - "Absent pmin/pmax/sigma preserve the existing p2/p98 + 2.0-sigma behavior"
    - "DEM layers (render_params starts with algorithm=) never receive a stretch rescale"
    - "SPIKE-01 is closed with evidence recorded in 1153-SPIKE.md (no re-spike)"
  artifacts:
    - path: "backend/app/processing/tiles/router.py"
      provides: "Multi-band n_bands fix + pmin/pmax/sigma params + bounds-keyed stats cache + dynamic percentile-key selection + 422 validation"
      contains: "_band_stats_cache"
    - path: "backend/tests/test_raster_colormap_proxy.py"
      provides: "Unit tests: 3-fragment multi-band, percentile-key selection, cache-key isolation, 422 invalid bounds, default preservation"
      contains: "rescale="
  key_links:
    - from: "raster_tile_proxy"
      to: "_fetch_band_statistics"
      via: "forwarded pmin/pmax + repeated p= raw_query_suffix"
      pattern: "_fetch_band_statistics"
    - from: "raster_tile_proxy"
      to: "_compute_stretch_rescale"
      via: "n_bands=min(band_count or 1, 3), sigma, pmin, pmax"
      pattern: "_compute_stretch_rescale"
    - from: "raster_auth_check"
      to: "raster_tile_proxy"
      via: "X-GeoLens-Band-Count response header"
      pattern: "X-GeoLens-Band-Count"
---

<objective>
Backend-only: make the raster tile proxy compute an independent per-band rescale for
multi-band rasters (RASTER-STRETCH-03) and accept configurable percentile/sigma bounds
that are correctly isolated in the stats cache (RASTER-STRETCH-UI-01 backend). Close
SPIKE-01 against the recorded evidence (already RESOLVED in 1153-SPIKE.md — do NOT re-spike).

Purpose: a 3-band ortho must produce 3 `rescale=` fragments, and changing `pmin` from 2 to 5
must actually change the served tiles instead of serving stale cached p2/p98 stats.
Output: edited `backend/app/processing/tiles/router.py` + new unit tests in
`backend/tests/test_raster_colormap_proxy.py`, focused backend pytest green.

Scope guard: BACKEND ONLY. No frontend changes (those land in phase 1154). The DEM
`algorithm=terrainrgb` / `is_dem` guard must be preserved unchanged — stretch never applies to DEM.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-CONTEXT.md
@.planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-SPIKE.md

<interfaces>
<!-- Key contracts the executor needs. Extracted from the codebase — use directly, no exploration needed. -->

backend/app/platform/storage/titiler_url.py:
```python
def build_titiler_cog_url(
    endpoint: str,
    *,
    query: dict[str, str] | None = None,
    raw_query_suffix: str | None = None,
) -> str: ...
```
`query` is urlencoded and CANNOT express repeated keys. `raw_query_suffix` is appended
verbatim (after stripping a leading "?"/"&") and is the mechanism for repeated keys such
as `p=2&p=98`.

backend/app/processing/tiles/router.py (current state — the file to modify):
```python
_band_stats_cache: LRUCache[str, list[dict] | None] = LRUCache(maxsize=256)  # ~line 241

async def _fetch_band_statistics(open_path: str) -> list[dict] | None:  # ~line 244
    # cache keyed on open_path only; builds statistics URL with query={"url": open_path}
    # parses Titiler "b1","b2",... keys ordered by int suffix

def _compute_stretch_rescale(bands: list[dict], stretch: str, n_bands: int) -> list[str]:  # ~line 272
    # loops range(n_bands); percentile reads HARDCODED b.get("percentile_2")/("percentile_98")
    # stddev uses module-level _STDDEV_SIGMA = 2.0; returns one "rescale=lo,hi" per band

_STDDEV_SIGMA = 2.0  # ~line 233 (module-level default)
```
Stretch call site in `raster_tile_proxy` (~line 578-590):
```python
if stretch and stretch != "minmax" and not render_params.startswith("algorithm="):
    bands = await _fetch_band_statistics(open_path)
    rescale_parts = _compute_stretch_rescale(bands, stretch, n_bands=1) if bands else []  # <-- HARDCODED n_bands=1
    ...
```
`raster_auth_check` (~line 445) returns `row` from `_resolve_raster_access`; `row["band_count"]`
is available there and emits headers `X-GeoLens-Asset-OpenPath` / `X-GeoLens-Render-Params`.
`raster_tile_proxy` (~line 510) currently reads only those two headers from the auth response.
</interfaces>

<test_seam>
<!-- From backend/tests/test_raster_colormap_proxy.py — existing test patterns to reuse. -->
- `_make_auth_response(open_path, render_params)` returns a MagicMock with the
  `X-GeoLens-*` headers. Extend it to also carry `X-GeoLens-Band-Count`.
- Tests `monkeypatch.setattr(tiles_router, "raster_auth_check", _fake_auth_check)` and
  `monkeypatch.setattr(tiles_router, "_titiler_client", mock_client)`.
- `tiles_router._band_stats_cache.clear()` is called in setup/teardown.
- Assertions inspect the built Titiler URL captured from the mocked `_titiler_client.get`.
- `_BAND_STATS` fixture has a single `b1` dict; add `b2`/`b3` entries and additional
  `percentile_5`/`percentile_95` keys for the new tests.
- No live Titiler dependency — all stats come from the mocked client.
</test_seam>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Multi-band rescale — replace hardcoded n_bands=1 with min(band_count or 1, 3)</name>
  <files>backend/app/processing/tiles/router.py, backend/tests/test_raster_colormap_proxy.py</files>
  <read_first>
  - backend/app/processing/tiles/router.py (read `raster_auth_check` ~445-503, the
    stretch call site ~578-590, `_compute_stretch_rescale` ~272-306, `_resolve_raster_access`
    SELECT which already returns `band_count`)
  - backend/tests/test_raster_colormap_proxy.py (`_make_auth_response`, `_BAND_STATS`,
    `_patch_auth_check`, `_patch_titiler_client`, cache-clear setup)
  - .planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-SPIKE.md
    (multi-band stats shape: b1/b2/b3 keys, distinct per-band percentile_*)
  </read_first>
  <behavior>
    - Test: 3-band raster (band_count=3) + stretch=percentile → built Titiler URL contains
      exactly 3 `rescale=` fragments (one per band, each from that band's percentile_2/98).
    - Test: 1-band raster (band_count=1) + stretch=percentile → exactly 1 `rescale=` fragment
      (preserves current single-band behavior).
    - Test: band_count=4 capped at 3 → exactly 3 `rescale=` fragments (Titiler render selects bidx 1-3).
    - Test: band_count missing/None → falls back to 1 fragment (no crash).
  </behavior>
  <action>
  In `raster_auth_check`, emit a new response header `X-GeoLens-Band-Count` carrying
  `str(row["band_count"] or 1)` alongside the existing `X-GeoLens-*` headers (this is the
  seam that gets band_count into `raster_tile_proxy` without re-querying the DB; the existing
  test mock seam is header-based so reuse it). In `raster_tile_proxy`, read
  `band_count = int(auth_resp.headers.get("X-GeoLens-Band-Count", "1") or 1)`.
  At the stretch call site (~line 581), change `n_bands=1` to
  `n_bands=min(band_count or 1, 3)`. Do NOT modify `_compute_stretch_rescale`'s loop —
  it already iterates `range(n_bands)` and breaks at `i >= len(bands)`. Do NOT touch the
  DEM branch (`render_params.startswith("algorithm=")` already short-circuits stretch).
  In tests: extend `_make_auth_response` to accept/emit `X-GeoLens-Band-Count` (default "1"),
  and extend `_BAND_STATS` to include distinct `b2`/`b3` dicts. Add the 4 tests above.
  </action>
  <verify>
    <automated>set -a && source backend/../.env.test 2>/dev/null; cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_raster_colormap_proxy.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - For band_count=3 + stretch=percentile, the captured Titiler URL has exactly 3
      occurrences of the substring `rescale=` (assert `url.count("rescale=") == 3`).
    - For band_count=1, exactly 1 `rescale=` fragment.
    - For band_count=4, exactly 3 `rescale=` fragments (cap enforced).
    - For band_count None/absent, exactly 1 `rescale=` fragment, no exception.
    - The DEM test (`test_dem_render_params_colormap_not_appended` and any stretch+DEM case)
      still passes — no `rescale=` injected when render_params starts with `algorithm=`.
    - Existing tests in test_raster_colormap_proxy.py remain green.
  </acceptance_criteria>
  <done>raster_tile_proxy uses n_bands=min(band_count or 1, 3); multi-band produces N (≤3) rescale fragments; DEM guard intact; new + existing tests green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Configurable bounds — pmin/pmax/sigma params, bounds-keyed cache, dynamic percentile keys, 422 validation</name>
  <files>backend/app/processing/tiles/router.py, backend/tests/test_raster_colormap_proxy.py</files>
  <read_first>
  - backend/app/processing/tiles/router.py (`raster_tile_proxy` signature ~510-526 with the
    existing `colormap_name`/`stretch` Query params, the colormap 422 guard ~553-557,
    `_fetch_band_statistics` ~244-269, `_compute_stretch_rescale` ~272-306, `_STDDEV_SIGMA` ~233)
  - backend/app/platform/storage/titiler_url.py (`build_titiler_cog_url` raw_query_suffix arg)
  - backend/tests/test_raster_colormap_proxy.py (the stretch/422 test patterns, _BAND_STATS,
    `_band_stats_cache.clear()` seam)
  - .planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-SPIKE.md
    (confirms p=5&p=95 → percentile_5/percentile_95; cache-key-must-include-bounds finding)
  </read_first>
  <behavior>
    - Test: stretch=percentile&pmin=5&pmax=95 → _fetch_band_statistics builds a statistics
      URL whose raw query contains `p=5&p=95`; rescale uses percentile_5/percentile_95.
    - Test: cache isolation — two calls for the same open_path with (pmin=2,pmax=98) then
      (pmin=5,pmax=95) create two distinct _band_stats_cache entries keyed
      `(open_path, pmin, pmax)`; the second call does NOT return the first's cached bands.
    - Test: stretch=stddev&sigma=3 → rescale computed with mean ± 3·std (not 2·std).
    - Test: defaults — stretch=percentile with NO pmin/pmax → percentile_2/percentile_98
      (unchanged); stretch=stddev with NO sigma → 2.0·std (unchanged).
    - Test: 422 on pmin=95&pmax=5 (pmin>=pmax), pmin=-1, pmax=101, sigma=0, sigma=-1 —
      Titiler is NOT called (mock client get-count stays 0 for the tile fetch path).
  </behavior>
  <action>
  Add three Query params to `raster_tile_proxy`: `pmin: float | None`, `pmax: float | None`,
  `sigma: float | None` (all default None, with descriptions noting they configure the
  percentile clip and stddev multiplier; absent = current p2/p98 + 2.0σ).
  Validation (place BEFORE the stretch block, alongside the colormap 422 guard, so Titiler is
  never called on bad input): when stretch in {percentile, stddev} and any of pmin/pmax/sigma
  is supplied, validate — `pmin` defaults 2.0, `pmax` defaults 98.0, `sigma` defaults
  `_STDDEV_SIGMA`. Reject with HTTP 422 when NOT (`0 <= pmin < pmax <= 100`) or NOT (`sigma > 0`).
  Apply these checks unconditionally when the param is present (even if validation would only
  matter for the active stretch mode) so invalid input is always 422.
  Change `_fetch_band_statistics(open_path)` → `_fetch_band_statistics(open_path, pmin, pmax)`:
  cache key becomes the tuple `(open_path, pmin, pmax)`; build the statistics URL with
  `query={"url": open_path}` AND `raw_query_suffix=f"p={pmin}&p={pmax}"` (repeated key via the
  raw suffix — the query dict cannot hold repeated keys). Update the `_band_stats_cache` type
  annotation to `LRUCache[tuple, list[dict] | None]`.
  Change `_compute_stretch_rescale(bands, stretch, n_bands)` →
  `_compute_stretch_rescale(bands, stretch, n_bands, *, pmin, pmax, sigma)`: percentile branch
  reads `b.get(f"percentile_{_fmt(pmin)}")` / `b.get(f"percentile_{_fmt(pmax)}")` where the key
  format matches Titiler's response (integers render as `percentile_5`, not `percentile_5.0` —
  format the percentile to drop a trailing `.0`); stddev branch uses `sigma` instead of the
  module constant `_STDDEV_SIGMA`. Pass the resolved pmin/pmax/sigma defaults from the call site.
  Update the stretch call site to thread pmin/pmax/sigma into both `_fetch_band_statistics`
  and `_compute_stretch_rescale`. PRESERVE the DEM guard and the absent-param defaults exactly.
  In tests: add `percentile_5`/`percentile_95` keys to `_BAND_STATS` bands; add the 5 behaviors
  above. For cache-isolation, assert `(open_path, 2.0, 98.0)` and `(open_path, 5.0, 95.0)` both
  exist in `tiles_router._band_stats_cache` after the two calls.
  </action>
  <verify>
    <automated>cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_raster_colormap_proxy.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - pmin=5&pmax=95 → statistics URL raw query contains `p=5&p=95`; rescale derived from
      `percentile_5`/`percentile_95` (assert the resulting `rescale=` lo,hi match those keys).
    - After a (2,98) call then a (5,95) call on the same open_path, `_band_stats_cache` has
      both `(open_path, 2.0, 98.0)` and `(open_path, 5.0, 95.0)` keys (len == 2), and the two
      tile URLs carry different `rescale=` values.
    - sigma=3 produces rescale lo/hi = mean ± 3·std (clamped to band min/max), distinct from sigma=2.
    - With no pmin/pmax: percentile uses percentile_2/percentile_98. With no sigma: 2.0·std.
    - Each of pmin=95&pmax=5, pmin=-1, pmax=101, sigma=0, sigma=-1 returns HTTP 422 and the
      mocked Titiler tile-fetch client is not invoked for that request.
    - DEM (`algorithm=` render_params) still receives no rescale regardless of pmin/pmax/sigma.
  </acceptance_criteria>
  <done>pmin/pmax/sigma threaded end-to-end; cache keyed (open_path, pmin, pmax); dynamic percentile keys; 422 on invalid bounds before Titiler; defaults preserved; DEM untouched; tests green.</done>
</task>

<task type="auto">
  <name>Task 3: Close SPIKE-01 + focused backend pytest green + OpenAPI no-drift check</name>
  <files>backend/tests/test_raster_colormap_proxy.py</files>
  <read_first>
  - .planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-SPIKE.md
    (the RESOLVED evidence — this task references it as closure, does NOT re-run the spike)
  - backend/tests/test_raster_colormap_proxy.py (full file, after Tasks 1-2 edits)
  </read_first>
  <action>
  SPIKE-01 is ALREADY RESOLVED — evidence is in 1153-SPIKE.md (live Titiler `/cog/statistics`
  honors arbitrary `p=` params returning `percentile_<N>` keys; multi-band returns distinct
  b1/b2/b3 stats). Do NOT re-run the spike. This task is the closure/verification step:
  add a single docstring-documented test (or assertion) in test_raster_colormap_proxy.py named
  to reference SPIKE-01 that pins the contract the spike validated — i.e. that
  `_fetch_band_statistics` forwards `p=pmin&p=pmax` and that `_compute_stretch_rescale` reads
  `percentile_<pmin>`/`percentile_<pmax>` dynamically — citing 1153-SPIKE.md in the docstring as
  the live-evidence source. Then run the full focused raster/tile suite to confirm no regression,
  and run the OpenAPI drift check (the new params are query params on an existing binary-tile
  route; confirm whether the snapshot captures them — if `make openapi-check` reports drift,
  note it in the SUMMARY for the orchestrator rather than regenerating here unless trivially clean).
  </action>
  <verify>
    <automated>cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_raster_colormap_proxy.py tests/test_raster_tiles.py tests/test_titiler_url_helper.py -q</automated>
  </verify>
  <acceptance_criteria>
    - test_raster_colormap_proxy.py contains a test whose name/docstring references SPIKE-01 and
      cites 1153-SPIKE.md as the live-evidence source, pinning the p=/percentile_<N> contract.
    - The focused suite (test_raster_colormap_proxy.py + test_raster_tiles.py +
      test_titiler_url_helper.py) passes with 0 failures.
    - The SUMMARY records the `make openapi-check` result (no-drift expected; if drift, the
      orchestrator is notified rather than a silent regen).
  </acceptance_criteria>
  <done>SPIKE-01 closed with cited evidence and a contract-pinning test; focused raster/tile pytest green; OpenAPI drift status recorded.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client → raster_tile_proxy | Untrusted `pmin`/`pmax`/`sigma`/`stretch`/`colormap_name` query params cross here |
| raster_tile_proxy → internal Titiler | App forwards a built `/cog/statistics` + tile URL to the internal-only Titiler service |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1153-01 | Tampering | `pmin`/`pmax`/`sigma` query params on raster_tile_proxy | mitigate | Validate `0 <= pmin < pmax <= 100` and `sigma > 0`; reject with HTTP 422 BEFORE any Titiler call (Task 2). |
| T-1153-02 | Denial of Service | stale/unbounded `_band_stats_cache` under varied bounds | accept | Cache is already a bounded `LRUCache(maxsize=256)`; adding the bounds tuple to the key increases distinct entries but the LRU bound caps memory. Low risk — Titiler is internal-only. |
| T-1153-03 | Information Disclosure | DEM elevation values leaking via stretch rescale | mitigate | Preserve the `algorithm=terrainrgb` / `is_dem` guard — stretch never applies to DEM (Tasks 1-2 leave that branch untouched; tests assert no rescale on `algorithm=` render_params). |
| T-1153-SC | Tampering | npm/pip/cargo installs | mitigate | No new package installs in this phase — all changes use existing deps (httpx, cachetools, fastapi). No legitimacy checkpoint required. |
</threat_model>

<verification>
- `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_raster_colormap_proxy.py tests/test_raster_tiles.py tests/test_titiler_url_helper.py -q` → all green.
- 3-band input → exactly 3 `rescale=` fragments in the built Titiler URL.
- Different pmin/pmax → distinct `_band_stats_cache` keys + distinct `rescale=` values.
- Invalid bounds → HTTP 422, Titiler not called.
- DEM render_params (`algorithm=`) → no rescale injected.
- Absent pmin/pmax/sigma → current p2/p98 + 2.0σ preserved.
- SPIKE-01 closed via cited contract-pinning test (no re-spike).
</verification>

<success_criteria>
- RASTER-STRETCH-03: multi-band rasters produce up to 3 independent per-band `rescale=` fragments (capped at 3), pinned by a unit test asserting fragment count.
- RASTER-STRETCH-UI-01 (backend): `pmin`/`pmax`/`sigma` accepted, forwarded as repeated `p=` to `/cog/statistics`, percentile keys read dynamically, `_band_stats_cache` keyed by `(open_path, pmin, pmax)`, invalid bounds → 422, defaults preserved.
- SPIKE-01: closed against 1153-SPIKE.md evidence; no live spike re-run.
- DEM guard preserved; no frontend changes; focused backend pytest green.
</success_criteria>

<output>
Create `.planning/phases/1153-backend-multiband-stretch-configurable-bounds/1153-01-SUMMARY.md` when done.
</output>
