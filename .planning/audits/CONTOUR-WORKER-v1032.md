# Contour Worker Spike — v1032 Phase 1144 (CONTOUR-01)

**Date:** 2026-05-28
**Author:** Claude (orchestrator-driven Playwright MCP)
**Requirement:** CONTOUR-01 (spike) → feeds CONTOUR-02 (disposition)
**Verdict:** **CUT** the contour control (evidence below; harden path is not "clearly cheap").

---

## 1. Reproduction (live, orchestrator-driven MCP)

- **Target:** builder map `8dd6a129-8eb0-4ba9-b421-716c83b160dd` ("Adirondack High Peaks — 3D Relief"), DEM dataset `raster_5ef1387b8bde45e3` (`catalog.raster_assets.is_dem=true`), z14.
- **Method:** frontend is Vite dev (HMR + source bind-mount). Temporarily flipped `CONTOUR_CONTROL_ENABLED=true` (`DEMEditorScene.tsx:28`), switched the DEM layer to Hillshade render mode (contour control is gated to hillshade/terrain), toggled the "Contour lines" switch.
- **Result:** **exactly 28 errors + 28 warnings on every enable** — deterministic. Toggled off→on a second time → another 28/28 (28 → 56 cumulative). Baseline before enable: 0 errors. After reverting the flag + reload: 0 new errors.
- **The flag flip was reverted** (`git diff` clean) and the repro edits were **never saved** (DB confirms DEM layer `render_mode` NULL, no `_contour-enabled` paint key). Zero residue.

## 2. Error Inventory (by category)

| Category | Count per enable | Source | Detail |
|----------|------------------|--------|--------|
| Malformed contour-tile `Request` | 28 | `maplibre-contour` worker → MapLibre source loader, caught by `BuilderMap.tsx:352` `map.on('error')` handler | `Failed to construct 'Request': Failed to parse URL from http://localhost:8080dem1-contour://14/4830/5949?contourLayer=contours&elevationKey=ele&levelKey=level&overzoom=1&thresholds=11*100*500~13*50*100~9*500` |

- Each of the 28 is one contour vector tile in the z14 viewport (`dem1-contour://14/{x}/{y}`), x∈[4827..4830], y∈[5946..5950].
- The 28 paired `[WARNING] [BuilderMap] Map error:` entries are the same events logged by the BuilderMap error handler — **not a second fault**.
- **All HTTP traffic during repro was 200/204** (561× 200, 87× 204; the DEM `.png` raster tiles loaded fine). This is **not** a tile-fetch, auth, 404, or encoding-decode failure.

## 3. Root Cause

The smoking gun is the malformed URL: **`http://localhost:8080dem1-contour://14/4830/5949?...`**

- `maplibre-contour`'s `DemSource.contourProtocolUrl()` returns a **custom-protocol** tile URL of the form `dem1-contour://{z}/{x}/{y}?...` (`dem1` = the lib's internal shared-DEM protocol id). It registers a handler for that scheme via `maplibre.addProtocol(...)` in `setupMaplibre` (`contour-sync.ts:99`).
- Under **maplibre-gl 5.24.0**, the vector-source tile loader does **not** route these `dem1-contour://` URLs through the registered `addProtocol` handler. Instead it treats the URL as a **relative HTTP URL** and resolves it against the page origin → `http://localhost:8080` + `dem1-contour://...` = `http://localhost:8080dem1-contour://...`, which then fails `new Request()` construction. One `error` event fires per contour tile.
- This is a **`maplibre-contour@0.1.0` ↔ `maplibre-gl@5.x` custom-protocol incompatibility.** maplibre-contour 0.1.0 predates maplibre-gl 5.x's protocol/worker source-loading changes.
- It is **distinct from the already-fixed `716b1927` bug** (that fix corrected passing a Map instance to `setupMaplibre` instead of the module `addProtocol`; that fix is present and correct at `contour-sync.ts:99`). The protocol is now *registered* correctly — but maplibre-gl 5.x does not *consult* it for this source's tile loading.

## 4. Harden Path — effort assessment

Hardening is **NOT "clearly cheap"** (the REQUIREMENTS.md decision threshold):

| Harden option | Effort / risk |
|---------------|---------------|
| **Bump `maplibre-contour` to a compatible version** | ❌ **Impossible — 0.1.0 is the latest published version** (registry: 0.0.2→0.1.0, nothing newer). The library declares **no `maplibre-gl` peerDependency** and is effectively dormant at 0.x. No upstream fix is available. |
| **Fork / patch maplibre-contour's protocol + URL generation** for maplibre-gl 5.x | High risk + ongoing maintenance burden on an unmaintained pre-1.0 dep; requires reverse-engineering maplibre-gl 5.x's v5 worker source-loading + custom-protocol resolution. Multi-day, open-ended. |
| **Reimplement client-side contour generation** without maplibre-contour | Feature-milestone-sized (worker, marching-squares/isoline generation, MVT encoding). Far beyond a hygiene tail. |

## 5. Recommendation — **CUT**

Cut the contour control cleanly in Phase 1145 (CONTOUR-02):

1. Remove `maplibre-contour` from `frontend/package.json` (+ lockfile).
2. Delete `frontend/src/components/builder/contour-sync.ts` + `__tests__/contour-sync.test.ts`.
3. Remove the `syncContourLayer` import + call site at `map-sync.ts:918-919`.
4. Delete the `CONTOUR_CONTROL_ENABLED` flag + the gated CONTOUR LINES block in `DEMEditorScene.tsx` + the 5 `it.skip` dormant tests in `DEMEditorScene.test.tsx`.
5. Add a positive regression pin asserting the DEM editor renders no contour control.

**Rationale:**
- No compatible upstream fix exists (terminal 0.1.0); hardening means owning a fork or reimplementing — not justified for a hygiene milestone.
- Contour lines on a DEM are a **nice-to-have cartographic feature**, not core to the catalog's "find any dataset in seconds" value.
- Keeping dormant code + an incompatible 0.x dep + 5 skipped tests across milestones is **debt masquerading as a nearly-done asset** — the exact thing v1032 set out to resolve.
- If contour is genuinely wanted later, it should return as a scoped feature on a maintained approach (Out of Scope note in REQUIREMENTS.md already records this).

---

*Spike reproduced and root-caused live via orchestrator-driven Playwright MCP, 2026-05-28. Temp `CONTOUR_CONTROL_ENABLED` flip reverted; zero residue.*
