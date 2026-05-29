# Phase 1145: Contour Disposition - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Execute the Phase 1144 spike disposition: **CUT** the contour control. Requirement **CONTOUR-02**.

Decision basis (`.planning/audits/CONTOUR-WORKER-v1032.md`): `maplibre-contour@0.1.0` is the terminal published version and its `dem1-contour://` custom-protocol tile URLs are not routed by maplibre-gl 5.x (resolved as relative HTTP → malformed `Request` → 28 errors/enable). No compatible upgrade; harden = fork/patch or reimplement (not clearly cheap). Default bias → CUT.
</domain>

<decisions>
## Implementation Decisions

### The cut (exhaustive surface list from grep)
1. `frontend/package.json:44` — remove `"maplibre-contour": "^0.1.0",` + update lockfile.
2. DELETE `frontend/src/components/builder/contour-sync.ts` (219 LOC).
3. DELETE `frontend/src/components/builder/__tests__/contour-sync.test.ts` (360 LOC).
4. `frontend/src/components/builder/map-sync.ts` — remove `import { syncContourLayer } from './contour-sync'` (line 16) and the `syncContourLayer(...)` call (line 919). KEEP the `is_dem` block + `syncColorReliefLayer` (shipped EDITOR-DEM-05 hypsometric tint).
5. `frontend/src/components/builder/DEMEditorScene.tsx` — remove the `CONTOUR_CONTROL_ENABLED` flag + its doc comment (lines 22-28) and the entire gated CONTOUR LINES `<section>` (lines 423-482). KEEP shared helpers `getNumber`/`getString`/`handlePaintValue` (used by hillshade + hypso). Renumber the "4. HYPSOMETRIC TINT" comment → "3.".
6. `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx` — delete the 5 `it.skip` interaction tests (534-633) + the "re-enable in v1032" comment; KEEP and relabel the 3 "section is absent" tests (500-531) as the permanent cut regression pins.
7. i18n: remove the 5 contour keys (`sectionContourLines`, `contourEnable`, `contourInterval`, `contourColor`, `contourWeight`) from all 4 locales (en/de/es/fr `builder.json`) to keep parity + a clean cut.

### Verification
- `npm run typecheck` exit 0; `vitest` for DEMEditorScene (3 absence pins pass; contour-sync.test.ts gone); i18n parity 2/2.
- No backend changes (no backend contour path; `style_json.py` emits no contour).
</decisions>

<code_context>
## Existing Code Insights
- The DEM editor's contour `<section>` was gated behind `CONTOUR_CONTROL_ENABLED && (mode==='hillshade'||'terrain')` — never rendered in prod, so removing it is a no-op for shipped behavior.
- The 3 kept tests already assert `queryByText('CONTOUR LINES')` is absent in image/hillshade/terrain — they convert directly into the "stays gone" regression pins.
</code_context>

<specifics>
## Specific Ideas
Clean cut, no half-wired state. After the cut, `grep -rn "contour" frontend/src` should return zero matches (case-insensitive, excluding unrelated words).
</specifics>

<deferred>
## Deferred Ideas
Contour as a future feature on a maintained approach is recorded in REQUIREMENTS.md Out of Scope.
</deferred>
