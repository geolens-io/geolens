# Phase 1059: Basemap Sublayer Editor (Path B FIX) - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning
**Mode:** Auto-generated under workflow.skip_discuss=true; merging discuss + UI design from REQUIREMENTS.md + scout

<domain>
## Phase Boundary

Restore per-sublayer styling overrides for basemap sublayers (stroke color, stroke width, casing color, casing width, zoom range, opacity) with **real persistence** through `MapBasemapConfig.sublayer_overrides` jsonb-additive. Overrides must round-trip through save/reload and apply correctly across all 4 render contexts: builder, viewer (`/m/{id}`), shared link (`/m/{token}`), and embed (`/embed/{token}`).

**Background:** The styling surface was originally introduced in v1008 (Phase 1038) as dead-wired stubs — 5 callbacks `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange` were `TODO(BUILDER-SUBLAYER-PERSIST)` no-ops. v1011.1 Phase 1052 EMRG-FN-01 chose **Path A REMOVE** (commits `3629ec04` + `3e48d331`) for hygiene close, deleting the dead stubs while preserving the live `onOpacityChange` and `onResetSublayer` callbacks. Phase 1059 is the **Path B FIX** — bring the surface back with a working persistence path.

**In scope:**
- Backend: extend Pydantic `BasemapConfig` schema (`backend/app/modules/catalog/maps/schemas.py:182`) with `sublayer_overrides: dict[str, SublayerOverride] | None` field (jsonb-additive — no migration; existing `basemap_config` jsonb column at `backend/app/modules/catalog/maps/models.py:82` already stores the parent dict)
- Backend: persist + retrieve `sublayer_overrides` through the existing map save/load endpoints (POST `/maps/`, PATCH `/maps/{id}`, GET `/maps/{id}`); validators tolerate unknown keys for forward-compat
- Frontend: extend `MapBasemapConfig` interface at `frontend/src/types/api.ts:27` to mirror backend schema
- Frontend: restore the controls in `BasemapSublayerEditorScene.tsx` — stroke color picker, stroke width slider, casing color picker, casing width slider, zoom range (min/max), and the existing opacity slider untouched
- Frontend: wire callbacks to `useMapBuilderStore` (or sibling store) so changes update `basemap_config.sublayer_overrides[sublayer_id]` and trigger the existing autosave path
- Frontend MapLibre integration: apply overrides at style-mutation time in all 4 render contexts. Single shared helper that takes `sublayer_overrides` + MapLibre `map` instance and rewrites `paint`/`layout` properties for affected sublayers
- Cross-context tests: vitest unit tests covering builder render + viewer render + shared link render + embed render with overrides applied
- i18n parity: all 4 locales (en/de/es/fr) updated for new control labels (most labels already existed in v1008 before EMRG-FN-01 removal — restore from git if cleaner than re-translating)

**Not in scope:**
- New basemap providers (REQUIREMENTS.md Out of Scope)
- MapLibre style properties beyond fill/stroke/casing/zoom/opacity (e.g., dash patterns, line caps, text-font for label sublayers — REQUIREMENTS.md Out of Scope row)
- Per-sublayer detail-level pills (Phase 1051 INV-01 already disposed; explicit comment block at `BasemapSublayerEditorScene.tsx:15` documents the prior disposition)
- Server-side rendering of overrides (only frontend MapLibre applies them; backend just persists)
- Migration of "legacy maps" — they load with `sublayer_overrides=undefined` and render with default basemap styling (zero-migration backward compat per REQUIREMENTS.md acceptance criterion 4)

</domain>

<decisions>
## Implementation Decisions

### Persistence Path (Backend)

- **D-01:** **Extend Pydantic `BasemapConfig`** at `backend/app/modules/catalog/maps/schemas.py:182` with a new optional field `sublayer_overrides: dict[str, SublayerOverride] | None = None`. The keying is by **sublayer ID** (string identifiers per the existing `BasemapSublayer` taxonomy — e.g., `'road'`, `'boundary'`, `'building'`, plus any sub-IDs the renderer exposes). Backend treats the dict as **opaque-ish** — validates the SublayerOverride schema per-value but does not enforce that keys map to known sublayer IDs (forward-compat for new sublayers added in future basemap providers).
- **D-02:** **`SublayerOverride` Pydantic model** captures the 6 styling axes:
  - `stroke_color: str | None` (hex `#RRGGBB` or `null` = use basemap default)
  - `stroke_width: float | None` (pixels, `0..20`, `null` = default)
  - `casing_color: str | None` (hex `#RRGGBB` or `null`)
  - `casing_width: float | None` (pixels, `0..20`, `null`)
  - `min_zoom: float | None` (`0..24`, `null`)
  - `max_zoom: float | None` (`0..24`, `null`)
  - `opacity: float | None` (`0..1`, `null` = use basemap default; existing top-level `BasemapConfig.opacity` controls the WHOLE basemap, this per-sublayer opacity is additive)
  Pydantic field validators clamp to ranges; missing fields default to `None` (= use basemap default). All fields nullable so partial overrides are valid.
- **D-03:** **Storage:** the existing `Map.basemap_config: jsonb` column at `backend/app/modules/catalog/maps/models.py:82` already accepts opaque dicts. Adding `sublayer_overrides` is a schema-level change inside the Pydantic model only — **no Alembic migration needed**, no DB schema change. Legacy `basemap_config` payloads without `sublayer_overrides` deserialize cleanly (Pydantic default = `None`).
- **D-04:** **Endpoints that already accept `basemap_config`** (POST `/maps/`, PATCH `/maps/{id}`, save endpoint) automatically pick up the new field via Pydantic. The map service layer at `service.py` round-trips the dict opaquely (already does this for the parent `BasemapConfig`). No new endpoint needed.

### Frontend Render Pipeline

- **D-05:** **Single shared helper `applySublayerOverrides(map: maplibregl.Map, overrides: Record<string, SublayerOverride> | undefined, basemap_provider_id: string)`** exported from `frontend/src/lib/builder/basemap-style-mutation.ts` (NEW file, sibling to existing builder helpers). Helper is called:
  - In `BuilderMap.tsx` after the basemap style loads + after every `sublayer_overrides` change
  - In `ViewerMap.tsx` (`/m/{id}`) after style load
  - In `SharedMap.tsx` and `EmbedMap.tsx` (paths TBD by planner) after style load
  Helper mutation uses `map.setPaintProperty(layer_id, ...)` and `map.setLayerZoomRange(layer_id, min, max)`. **No declarative `<Layer>` props** — direct imperative mutation per the project's `@vis.gl/react-maplibre v8 + onLoad imperative pattern` memory.
- **D-06:** **Layer ID resolution:** the helper needs a mapping from semantic sublayer ID (`'road'`) to the actual MapLibre layer IDs that the current basemap provider exposes (e.g., `road-primary`, `road-secondary`, ...). This mapping already exists somewhere (used by `road_visibility` mode) — **scout and reuse** rather than rebuild. Likely at `frontend/src/lib/basemap-utils.ts` or `basemap-style-mutation.ts`.
- **D-07:** **Override application order:** overrides apply AFTER the existing visibility-mode mutations (road_visibility, boundary_visibility, building_visibility) so that selective styling sits on top of the visibility toggle. This means if a sublayer is hidden by visibility mode, the override still updates paint but the layer remains invisible — clean semantics.

### Frontend Editor Scene UI (UI-Spec inline since workflow.skip_discuss=true)

- **D-08:** **Component:** restore `BasemapSublayerEditorScene` to the v1008 shape that existed before commit `3629ec04`. Git-restore the v1008 component as a starting point, then update prop types to match the new persistence path. Keep `onOpacityChange` and `onResetSublayer` unchanged (live consumers; preserve from current EMRG-FN-01 state).
- **D-09:** **Sections (top to bottom):**
  1. **STROKE** — color picker (HexColorInput from existing UI primitives; if none, add a lightweight one) + width slider (0..20px, 0.5 step)
  2. **CASING** — color picker + width slider (same scale as STROKE)
  3. **ZOOM RANGE** — min + max sliders (0..24, 0.5 step) with linked tooltip showing the active range
  4. **OPACITY** — existing slider (untouched)
  5. **RESET** — existing button (untouched, resets only the per-sublayer overrides for the selected sublayer)
- **D-10:** **Live preview:** every control change triggers immediate MapLibre style mutation (no debounce on the slider drag-handle release — instant feedback). Save to backend is debounced at the existing autosave layer (typically 500ms or onBlur). This matches the v1010 Plan PB-04 motion-token + debounce pattern.
- **D-11:** **Reset button scope:** Reset for a specific sublayer clears `basemap_config.sublayer_overrides[sublayer_id]` only — does not affect other sublayers. Top-level basemap settings (label_mode, road_visibility, etc.) untouched.

### Tests (vitest + headless playwright; NO live MCP)

- **D-12:** **Vitest coverage:**
  - `BasemapSublayerEditorScene.test.tsx` — extend the existing test file with new prop assertions (stroke/casing/zoom callbacks fire with concrete values)
  - `BuilderMap.test.tsx` — verify `applySublayerOverrides` is called after style load + after override change (mock map.setPaintProperty)
  - `ViewerMap.basemap-config.test.tsx` — already exists; extend to assert overrides apply with the new field
  - **NEW** `basemap-style-mutation.test.ts` — unit tests for `applySublayerOverrides` covering all 6 override fields + null-passthrough + zoom range
  - **NEW** `sublayer_overrides.round-trip.test.ts` (or integrate into existing map-config round-trip suite) — payload survives save→load
- **D-13:** **Backend pytest:** add 1 file `tests/test_basemap_sublayer_overrides.py` covering Pydantic validation, round-trip through the map service, legacy `basemap_config` without `sublayer_overrides` deserializes cleanly. Don't add e2e — Phase 1060 live MCP re-verify will exercise.

### Scope Guardrails (DO NOT widen)

- **D-14:** No new MapLibre style properties (no dash patterns, line caps, text-font, halo blur). Locked by REQUIREMENTS.md Out of Scope row.
- **D-15:** No new basemap providers. Locked by REQUIREMENTS.md Out of Scope row.
- **D-16:** No server-side rendering of overrides (e.g., no static-tile pre-rendering with overrides applied). Frontend-only.
- **D-17:** No retroactive backfill of legacy maps with override defaults — they render with `undefined`/default styling.
- **D-18:** No per-sublayer DETAIL LEVEL pills (Phase 1051 INV-01 dispositioned; do not resurrect).

### Anticipated Plan Split (Planner Refines)

- **D-19:** Four plans expected (planner may merge or split):
  1. **Plan 1059-A — Backend persistence:** Pydantic `SublayerOverride` model, `BasemapConfig.sublayer_overrides` field, tests for serialize/deserialize + round-trip + legacy compat. Small-medium plan.
  2. **Plan 1059-B — Frontend MapLibre integration:** `applySublayerOverrides` helper, wire into BuilderMap + ViewerMap + Shared + Embed contexts, unit tests for the helper + integration tests for each context. Medium plan, the riskiest (4 render contexts).
  3. **Plan 1059-C — Frontend editor UI:** Restore `BasemapSublayerEditorScene` stroke/casing/zoom sections, color picker primitive (if missing), wire callbacks to autosave path. Medium plan.
  4. **Plan 1059-D — Cross-context tests + i18n:** Round-trip tests, ViewerMap.basemap-config tests, 4-locale i18n parity, headless e2e spec. Small plan.
- **Wave structure:** A and B+C parallelizable (A is pure backend; B and C share `basemap-style-mutation.ts` indirectly but B writes it, C consumes it — serial). D depends on A+B+C.
  - Wave 1: Plan A (backend)
  - Wave 2: Plan B (style mutation helper) + Plan C (editor UI) — Plan B writes the helper, Plan C imports it; serial OR Plan C calls a stub that Plan B fills in
  - Wave 3: Plan D (cross-context tests + i18n)

### Claude's Discretion

- Choice of color picker primitive: search `frontend/src/components/ui/` for existing color input; if absent, add a minimal hex input wired to a native `<input type="color">` or a small react-colorful adapter (3-5 line wrapper). Planner decides.
- Whether to git-restore the v1008 `BasemapSublayerEditorScene` (commit `3629ec04^`) as the starting baseline, or rewrite from scratch using the current file as scaffolding. Planner decides based on diff size.
- Whether to make the override application a hook (`useApplySublayerOverrides`) or a pure function called from a useEffect. Pure function is simpler; hook is reusable. Planner decides.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of Truth

- `.planning/REQUIREMENTS.md` §"BSE-01" — full acceptance criteria
- `.planning/ROADMAP.md` Phase 1059 — goal, success criteria (4 items), depends_on, complexity estimate
- `.planning/STATE.md` §"v1013 Phase Map" — Phase 1059 entry
- Commits `3629ec04` + `3e48d331` (v1011.1 EMRG-FN-01) — Path A REMOVE commits; the source for git-restoring the v1008 component as a baseline
- Commit `6078b82a` (Phase 1051 INV-01) — DETAIL LEVEL pill removal; do NOT resurrect

### Established Patterns

- `feedback_review_findings_inline.md` — inline-fix posture; no v1013.1
- `project_maplibre_idle_retry_pattern.md` (memory) — MapLibre style mutations need `map.once('idle', ...)` recovery when `map.isStyleLoaded()` is false; the new `applySublayerOverrides` helper MUST handle this case
- `project_height_column_extrusion_convention.md` (memory) — sibling pattern for basemap layer styling at `minzoom=14` gate
- @vis.gl/react-maplibre v8 imperative pattern (memory) — declarative `<Source type="vector">` may be silently ignored; use imperative `map.addSource()` + `map.addLayer()`

### Code (touched)

- `backend/app/modules/catalog/maps/schemas.py:182` — `BasemapConfig` Pydantic model (extend with `sublayer_overrides`)
- `backend/app/modules/catalog/maps/models.py:82` — `Map.basemap_config` jsonb column (storage; no change)
- `backend/app/modules/catalog/maps/style_json.py:237` (`_clean_basemap_config`), `:905`, `:1225` — round-trip paths; verify they pass `sublayer_overrides` opaquely
- `backend/app/modules/catalog/maps/service_public.py:298, 348` — public service that exposes basemap_config to viewer/shared/embed
- `frontend/src/types/api.ts:27` — `MapBasemapConfig` interface (mirror new field)
- `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` — restore controls (see commit `3629ec04^` for v1008 baseline)
- `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` — extend tests
- `frontend/src/components/builder/BuilderMap.tsx` — apply overrides after style load
- `frontend/src/components/viewer/ViewerMap.tsx` — apply overrides after style load
- `frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx` — extend tests
- `frontend/src/pages/MapBuilderPage.tsx` — wire `sublayer_overrides` from store into BasemapSublayerEditorScene props
- `frontend/src/lib/basemap-utils.ts` (or sibling) — find the existing sublayer-ID-to-MapLibre-layer-ID mapping used by visibility modes
- `frontend/src/lib/builder/basemap-style-mutation.ts` (NEW) — `applySublayerOverrides` helper
- `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (or sibling) — control labels for stroke/casing/zoom

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`Map.basemap_config: jsonb` column** at `models.py:82` — already stores opaque dicts; adding nested `sublayer_overrides` is zero-migration
- **`BasemapConfig` Pydantic model** at `schemas.py:182` — straightforward field addition
- **`MapBasemapConfig` TypeScript interface** at `api.ts:27` — straightforward field addition
- **Opacity slider + Reset button** in current `BasemapSublayerEditorScene.tsx` (post-EMRG-FN-01) — preserved live consumers; the new STROKE/CASING/ZOOM sections sit alongside
- **v1008 baseline component** in commit `3629ec04^` — useful for restoring the visual scaffolding (Collapsible sections, Slider primitives)
- **`useMapBuilderStore` or sibling state store** — already handles `basemap_config` patches; extends to `sublayer_overrides[sublayer_id]` writes without new infrastructure
- **`useApplyBasemapConfig` (or sibling autosave path)** — already debounces backend save; the new override writes flow through the same path
- **`map.setPaintProperty` / `map.setLayerZoomRange`** — MapLibre imperative APIs we already use elsewhere
- **`@vis.gl/react-maplibre v8 onLoad` callback** — established pattern for imperative mutations

### Established Patterns

- **jsonb-additive backwards compat** (v1011 reinforced this) — no migration when adding optional dict fields to jsonb-stored Pydantic
- **MapLibre idle-retry** (memory file) — wrap mutations in `if (!map.isStyleLoaded()) { map.once('idle', ...); return; }` to avoid silent failures on fresh-add
- **Color hex input** — search project for existing primitive; v1008 used native `<input type="color">` per the dead-stub component
- **Slider primitive** at `frontend/src/components/ui/slider.tsx` (shadcn) — already used for opacity; reuse for width + zoom
- **Cross-context render parity tests** at `viewer/__tests__/ViewerMap.basemap-config.test.tsx` — established pattern for asserting basemap_config produces the expected MapLibre style mutations

### Integration Points

- Builder save → backend persist: existing autosave loop in `useMapBuilderStore` writes `basemap_config` patches; sublayer_overrides flow through unchanged
- Viewer/Shared/Embed render: `service_public.py:298, 348` exposes `basemap_config` to public-facing routes; the consumer components already read `MapBasemapConfig` from the map response
- Backend Pydantic validation: existing field validators on `BasemapConfig` apply; `SublayerOverride` adds its own ranges (`Field(ge=0, le=24)` for zoom, `ge=0, le=20` for widths, `ge=0, le=1` for opacity)

### Restart vs Rebuild

- Backend Python changes (schema field, validators) → `docker compose restart api worker` is sufficient. **NO Alembic migration needed for Phase 1059** (unlike Phase 1058's status enum extension).
- Frontend changes → Vite HMR.

</code_context>

<specifics>
## Specific Ideas

- **Restore v1008 baseline:** `git show 3629ec04^:frontend/src/components/builder/BasemapSublayerEditorScene.tsx > /tmp/v1008-component.tsx` — use as scaffolding. The pre-EMRG-FN-01 component had STROKE + CASING + zoom-range UI but no working persistence; Phase 1059 keeps the UI shape and adds the wire-up.
- **Test fixtures:** the v1011 ViewerMap.basemap-config.test.tsx already has a `BASEMAP_CONFIG` fixture (line 166). Extend it with `sublayer_overrides: { road: { stroke_color: '#ff0000', stroke_width: 2 } }` and assert MapLibre's `setPaintProperty('road-primary', 'line-color', '#ff0000')` is called.
- **Color picker:** if no project primitive, use `<input type="color">` with a hex text companion (a 10-line wrapper). Don't add a heavy dependency like react-colorful for a 3-5 control surface.

</specifics>

<deferred>
## Deferred Ideas

- **MapLibre style properties beyond fill/stroke/casing/zoom/opacity** (dash, line caps, text-font, halo blur) — REQUIREMENTS.md Out of Scope; defer to v1014+.
- **Per-sublayer DETAIL LEVEL pills** — Phase 1051 INV-01 dispositioned; do not resurrect.
- **Server-side rendering of overrides** — out of scope; frontend MapLibre only.
- **Override migrations / backfills for legacy maps** — they render with default basemap styling per acceptance criterion 4.
- **Override export to a portable style.json** — Phase 1059 persists in `basemap_config.sublayer_overrides` jsonb. Style.json export (PATCH `/maps/{id}/style.json`) is an existing feature that can pick this up later if needed.
- **Multi-basemap-provider override compatibility matrix** — Phase 1059 implements the mapping for whatever basemap providers are currently shipping; if a new provider exposes different sublayer IDs, the `sublayer_overrides` key set adapts naturally (opaque dict keys).
- **Live Playwright MCP re-verify of all 4 render contexts** — Phase 1060 close gate task. MCP currently disconnected for this session.

</deferred>

---

*Phase: 1059-Basemap Sublayer Editor Path B FIX*
*Context gathered: 2026-05-19 via auto-generated CONTEXT.md (workflow.skip_discuss=true) + scout pass + v1008 baseline review*
