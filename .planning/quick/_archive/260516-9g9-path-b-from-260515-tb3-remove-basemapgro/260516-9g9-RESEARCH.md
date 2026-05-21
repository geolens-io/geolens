---
quick_id: 260516-9g9
type: quick-task-research
status: ready-for-planning
researched: 2026-05-16
mode: blast-radius-cross-stack
predecessors: 260515-rdn, 260515-sqf, 260515-tb3
---

# Quick Task 260516-9g9: Path B — Remove BasemapGroupRow Row Slider + Master-Opacity Persistence — Blast-Radius Research

**Researched:** 2026-05-16
**Confidence:** HIGH — every line number verified by direct file read; runtime gap surfaced by file-level grep across `frontend/src/` for `masterOpacity` and `master_opacity`.
**Approach:** Decision is locked (CONTEXT.md). This document is a categorized cross-stack inventory of touchpoints, extending the §1–§8 shape of `260515-sqf-RESEARCH.md` with §1B (backend), §3B (migration check), §5B (runtime application gap), and §10 (public-API spot-check).

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Backend (Part 2):**
- Add `opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="Master basemap opacity 0.0–1.0")` to `BasemapConfig` at `backend/app/modules/catalog/maps/schemas.py:182`.
- NO Alembic migration. `maps.basemap_config` is a JSONB column; Pydantic default + `extra="forbid"` handle additive-field rollout cleanly.
- Investigate `style_json.py:243` (`_clean_basemap_config`) — confirm new field flows through automatically and decide whether to propagate to MapLibre style JSON or defer.

**Frontend Path A (Part 1) — BasemapGroupRow.tsx:**
- Remove `<Slider>` block (lines 181–203)
- Remove `Slider` import (line 5)
- Remove `onOpacityChange` from `BasemapGroupRowProps` interface (line 36)
- Remove `onOpacityChange` destructure (line 57)
- Remove `safeOpacity` local + `opacity` prop reference (line 64)
- Remove `opacity: number;` prop from interface (line 25) and `opacity,` destructure (line 48) — same reasoning as 260515-sqf §1 (no remaining consumer after slider goes)
- Update grid template `16px_14px_22px_22px_1fr_60px_22px` → `16px_14px_22px_22px_1fr_22px` (line 78; collapse 60px column)
- Update Cell 6/7 comments (lines 181, 205)

**Frontend Path A — UnifiedStackPanel.tsx:**
- Drop `opacity` + `onOpacityChange` from `BasemapGroupRowWrapperProps` interface (lines 231 + the `opacity` field on the wrapped `group` object, see §4 below — actually flows from `BasemapGroupInfo` so leave alone)
- Drop `onOpacityChange` from `BasemapGroupRowWrapper` destructure (line 251)
- Drop `onOpacityChange={onOpacityChange}` from `<BasemapGroupRow>` instantiation (line 282)
- Drop `onOpacityChange={() => {}}` NOOP wiring at `<BasemapGroupRowWrapper>` callsite (line 780)

**Frontend Path B (Part 2):**
- Replace TODO body at `MapBuilderPage.tsx:755-761` with `setMasterOpacity(opacity); layers.markDirty();`
- Replace load-side reset at `MapBuilderPage.tsx:469` with `setMasterOpacity(mapData.basemap_config?.opacity ?? 1)` — **NOTE:** load-side seeding actually belongs inside `use-builder-layers.ts:120` initializer because that's where `mapData.basemap_config` is read. The line 469 reset fires on `handleResetBasemapAppearance`, not on map load. See §5 below for the corrected wiring location.
- Include `opacity: masterOpacity` in the `basemap_config` payload sent at save — see §5 for exact location

**Side-finding (Part 3):**
- Edit `frontend/src/components/builder/hooks/use-layer-map-sync.ts:41-61` to gate `setHasUnsavedChanges(true)` on `if (updated)`.

**i18n:**
- `stackRow.opacitySlider` key STAYS in all 4 locales — consumer count goes from 2 today → 1 after task (only `BasemapGroupEditorScene.tsx:196` remains).
- **DO NOT touch any locale file.**

**Sketch doc:**
- Narrow `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` forward note (lines 34-44) from "basemap group rows and basemap-editor sublayer rows retain opacity slider" to "only basemap-editor sublayer rows retain a per-row opacity slider".
- Update group-row HTML example annotation (lines 163-178) since basemap groups no longer have one.

### Claude's Discretion

- Whether to surface the runtime application gap as a blocker (RECOMMENDED YES — see §5B).
- Whether to push runtime master-opacity application into the same task or split to follow-up (RECOMMENDED: split; see §5B + §12).
- Whether to extend `use-builder-save.test.ts` round-trip test vs. write a new test file (RECOMMENDED: extend; existing test at line 368 already exercises `basemap_config`).
- Sketch-doc forward-note narrowing wording (proposed in §9).

### Deferred Ideas (OUT OF SCOPE)

- Per-sublayer opacity in `BasemapGroupEditorScene` (already works per-sublayer; not redundant).
- `LayerEditorPanel` default-content opacity slider.
- Frontend default-value seeding for non-basemap layers.
- Data migration for existing maps' stored `basemap_config` (additive Pydantic default `1.0` handles this).
- Sublayer-state persistence (separate Phase 1038 follow-up).

---

## Phase Requirements (Path B scope)

| ID | Description | Research Support |
|----|-------------|------------------|
| PB-A1 | Backend `BasemapConfig.opacity: float` field added with default 1.0, ge=0.0, le=1.0 | §1B identifies exact insertion point and all 5 schema consumers |
| PB-A2 | Backend Pydantic tests prove default + bounds + extra-forbid still rejects unknowns | §3B identifies test files and existing patterns |
| PB-A3 | Backend round-trip test: PUT /maps with `basemap_config.opacity=0.55` → GET returns 0.55 | §3B identifies extension target |
| PB-B1 | BasemapGroupRow.tsx renders no row slider | §4 enumerates every line to remove |
| PB-B2 | UnifiedStackPanel.tsx no longer forwards `onOpacityChange` to BasemapGroupRow | §4 enumerates 4 lines to remove |
| PB-B3 | BasemapGroupRow.test.tsx drops opacity-related test + props | §7 enumerates test edits |
| PB-C1 | `setMasterOpacity` marks dirty + opacity persists across save/reload | §5 enumerates wire-up sites |
| PB-C2 | Round-trip vitest for masterOpacity persistence (extend `use-builder-save.test.ts`) | §7 identifies exact extension point |
| PB-D | `applyLayerUpdate` no longer marks dirty on non-matching layerId | §6 confirms safety + identifies test target |
| PB-S | Sketch doc + group-row HTML example narrowed | §9 |

---

## 1. Backend touchpoints

### `backend/app/modules/catalog/maps/schemas.py`

| Line(s) | What's there | Action |
|---------|--------------|--------|
| 182–208 | `class BasemapConfig(BaseModel)` definition with `label_mode`, `road_visibility`, `boundary_visibility`, `building_visibility`, `land_water_tone`, `relief_contrast`, plus `model_config = ConfigDict(extra="forbid")` (line 208) | **Add** `opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="Master basemap opacity 0.0–1.0")` between `relief_contrast` (line 203-206) and `model_config` (line 208). Field order convention in the file: lower-bound enums first, optional/nullable enum last, scalar last before `model_config`. Suggest inserting at line 207 (just before `model_config`). |

### Consumers of `BasemapConfig` (zero-touch — all flow through Pydantic automatically)

Verified via `grep -rn "BasemapConfig\b" backend/app/`:

| File | Line(s) | Usage | Action |
|------|---------|-------|--------|
| `backend/app/modules/catalog/maps/schemas.py` | 366, 400, 481, 672 | `MapCreate.basemap_config`, `MapUpdate.basemap_config`, `MapResponse.basemap_config`, `SharedMapResponse.basemap_config` — all typed as `BasemapConfig \| None` | **Leave alone** — Pydantic structural inheritance picks up the new field automatically on next request/response. |
| `backend/app/modules/catalog/maps/style_json.py` | 16 (import), 243 (`_clean_basemap_config`) | `BasemapConfig.model_validate(value).model_dump(mode="json")` — round-trips raw dict through Pydantic for shape normalization | **Leave alone** — passes opacity through automatically. **See §1B for the propagation-to-style-JSON question.** |

### 1B. `style_json.py:243` (the consumer-behavior investigation per CONTEXT.md)

**Function:** `_clean_basemap_config` at lines 237–245. Called from two places in `style_json.py`:
1. Line 905, inside `build_maplibre_style()` — emits `style.metadata.geolens.basemap_config` into exported MapLibre style JSON.
2. Line 1225, inside `parse_maplibre_style_import()` — rehydrates `basemap_config` from imported MapLibre style metadata.

**Behavior with the new opacity field:**
- `BasemapConfig.model_validate(value)` will accept `{...existing keys..., "opacity": 0.55}` and produce a model instance with the field set.
- `.model_dump(mode="json")` will include `"opacity": 0.55` in the output dict.
- Result: opacity ROUND-TRIPS through export/import of MapLibre style JSON automatically. **No code change in `style_json.py` is needed** for the persistence task.

**The deeper question CONTEXT.md raises:** should the master opacity also be *applied* to the rendered basemap layers in the exported MapLibre style JSON (e.g., as `raster-opacity` on raster basemap layers, or `paint.fill-opacity` on vector basemap layers)?

**Recommendation (Claude's discretion per CONTEXT.md):**
- **Do NOT propagate to style-JSON paint properties in this task.** Rationale:
  - The current frontend runtime ALSO does not propagate masterOpacity to maplibre paint properties — see §5B for the proof that `frontend/src/lib/basemap-utils.ts::applyBasemapConfigToStyle` ignores opacity entirely.
  - Adding the propagation to backend style-JSON export but not to the frontend runtime would produce divergent visual behavior between live editing (no visual effect) and exported style JSON (opacity baked into paint).
  - Bundling backend style-JSON propagation here drags style_json's per-layer paint-stamping logic into scope. That's a separate, larger change.
- **Defer style-JSON paint propagation to a follow-up task** that is paired with the frontend runtime application work (see §5B and §12).
- Persistence of `basemap_config.opacity` (Pydantic field + round-trip) is the only backend change in this task. Map style-JSON export will include opacity in the `style.metadata.geolens.basemap_config` block but NOT stamp it onto basemap layer paint.

### 1C. SQLAlchemy model — no change

`backend/app/modules/catalog/maps/models.py:82-84`:
```python
basemap_config: Mapped[dict | None] = mapped_column(
    JSONB, nullable=True, default=None
)
```

The column is `JSONB` with `nullable=True, default=None`. New Pydantic fields stored inside this dict require no DDL change. **Leave alone.**

---

## 2. Backend tests

### `backend/tests/test_maps.py`

| Line(s) | What's there | Action |
|---------|--------------|--------|
| 33-40 | `BASEMAP_CONFIG_PAYLOAD` fixture — currently has 6 keys, no `opacity` | **Add** `"opacity": 0.55` (any non-default value works) so all existing tests that reference this fixture exercise the new field via round-trip. **CAUTION:** adding to the shared fixture also affects test at line 526 (`test_update_map_rejects_extra_basemap_config_fields`); that test asserts unknown keys are rejected — should still pass because `opacity` is a *known* key after the schema change. |
| 498-516 | `test_update_map_round_trips_basemap_config` — already PUTs `BASEMAP_CONFIG_PAYLOAD` and GETs it back, asserts equality | **No edit needed** if `BASEMAP_CONFIG_PAYLOAD` is updated per above. The opacity round-trip is exercised automatically. Alternatively, **add a focused** `test_update_map_round_trips_basemap_opacity_field` that explicitly PUTs `{"basemap_config": {**BASEMAP_CONFIG_PAYLOAD, "opacity": 0.55}}` and asserts `resp.json()["basemap_config"]["opacity"] == 0.55` — recommended for clarity. |
| 223-229 | `test_create_map_defaults_basemap_config_to_null` — omitted basemap_config is null | **No edit** — unaffected. |
| 232-246 | `test_create_map_persists_basemap_config` — POSTs `BASEMAP_CONFIG_PAYLOAD` on create | **No edit** if fixture updated; or add explicit opacity assertion. |
| 518-530 | `test_update_map_rejects_extra_basemap_config_fields` — PUTs `{**BASEMAP_CONFIG_PAYLOAD, "raw_layers": []}`, asserts 422 | **No edit needed** — `raw_layers` is still unknown after the opacity addition. |
| 1515-1536 | `test_get_shared_map_includes_basemap_config` — public/shared map round-trip | **No edit** if fixture updated. |

### Recommended new Pydantic-validation tests

Add to `backend/tests/test_maps.py` (or a new module if you prefer schema isolation — `test_maps_schemas.py` does not currently exist). Pattern mirrors existing direct Pydantic tests elsewhere in the file:

```python
def test_basemap_config_opacity_defaults_to_one():
    from app.modules.catalog.maps.schemas import BasemapConfig
    cfg = BasemapConfig()
    assert cfg.opacity == 1.0

def test_basemap_config_opacity_accepts_valid_range():
    from app.modules.catalog.maps.schemas import BasemapConfig
    assert BasemapConfig(opacity=0.0).opacity == 0.0
    assert BasemapConfig(opacity=0.55).opacity == 0.55
    assert BasemapConfig(opacity=1.0).opacity == 1.0

def test_basemap_config_opacity_rejects_out_of_range():
    from app.modules.catalog.maps.schemas import BasemapConfig
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        BasemapConfig(opacity=-0.1)
    with pytest.raises(ValidationError):
        BasemapConfig(opacity=1.1)

def test_basemap_config_still_rejects_unknown_fields_with_opacity_set():
    from app.modules.catalog.maps.schemas import BasemapConfig
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        BasemapConfig(opacity=0.5, unknown_field=1)
```

**Note:** the verification gate command in CONTEXT.md says `pytest tests/test_maps.py tests/test_schemas.py -k basemap`. **`test_schemas.py` does not exist** in `backend/tests/` — only the per-domain files (`test_advanced_sharing_schema.py`, `test_commit_request_schemas.py`, etc.). The planner should drop the non-existent path or put new tests in `test_maps.py` (recommended — keeps schema + integration tests for the same domain in one file, matching how `test_create_map_persists_basemap_config` lives there).

### Test file for the import/export style-JSON path (verification only — no edit)

`backend/tests/test_maps_style_json.py:269` (`test_build_maplibre_style_exports_basemap_config_metadata`) and `:915` (`test_parse_maplibre_style_import_restores_basemap_config_from_metadata`) currently exercise the round-trip of `basemap_config` through MapLibre style export/import. **Recommend adding `"opacity": 0.55` to the test payloads at lines 271-281 and 923-936** so the export/import round-trip is exercised. **Not strictly required** (the existing test will continue to pass because opacity gets a default), but recommended for parity with the integration tests.

---

## 3. Backend migration check

**Conclusion: NO Alembic migration needed.**

Evidence:
- `backend/app/modules/catalog/maps/models.py:82-84` declares `basemap_config` as `JSONB, nullable=True, default=None`. JSONB columns store arbitrary JSON; field-level shape constraints live in Pydantic, not the DDL.
- Existing migration `backend/alembic/versions/0011_map_basemap_config.py` is the only DDL touching this column — it added it as untyped JSONB.
- Old rows: stored as `{"label_mode": "full", ..., "land_water_tone": "default"}` (no `opacity` key). Pydantic load via `BasemapConfig.model_validate(...)` will inject `opacity=1.0` (the new default) when no key is present. Backwards compatible.
- New rows: stored as `{...existing keys..., "opacity": 0.55}`. Pydantic accepts and serializes back unchanged.
- Edge: an old row with `{}` (empty dict) — would fail validation today already because `basemap_config` is opt-in (`None` is the "no config" state). Not relevant to this task.

**No SQLAlchemy model change. No Alembic revision. No data migration.**

---

## 4. Frontend Path A touchpoints

### `frontend/src/components/builder/BasemapGroupRow.tsx`

| Line(s) | What's there | Action |
|---------|--------------|--------|
| 5 | `import { Slider } from '@/components/ui/slider';` | **Remove import** (only consumer in the file is the slider being deleted) |
| 25 | `opacity: number;` in `BasemapGroupRowProps` interface | **Remove** (only the slider consumes it; mirror 260515-sqf §1 decision note on FolderGroupRow's `opacity` prop) |
| 36 | `onOpacityChange: (id: string, opacity: number) => void;` in `BasemapGroupRowProps` interface | **Remove prop** |
| 48 | `opacity,` destructure in component params | **Remove** |
| 57 | `onOpacityChange,` destructure in component params | **Remove** |
| 64 | `const safeOpacity = typeof opacity === 'number' && Number.isFinite(opacity) ? opacity : 1;` local | **Remove** (only consumer was the slider) |
| 78 | Grid template `'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center ...'` | **Update** → `grid-cols-[16px_14px_22px_22px_1fr_22px]` (collapse 60px slot — identical change to 260515-rdn/sqf) |
| 181–203 | `{/* Cell 6: Opacity slider */}` comment + the `eslint-disable-next-line` wrapper `<div>` with `onPointerDown` / `onClick` stopPropagation + child `<Slider>` element (`aria-label={t('stackRow.opacitySlider', ...)}`, `aria-valuetext`, `value`, `min`/`max`/`step`, `className="w-[60px]"`, `onValueChange={([value]) => onOpacityChange(groupId, ...)}`) | **Remove entire 23-line block** (Cell 6 disappears; Cell 7 kebab becomes Cell 6) |
| 205 | Comment `{/* Cell 7: Kebab menu — basemap variant with only 2 items */}` | **Update** to `{/* Cell 6: Kebab menu — basemap variant with only 2 items */}` |

### `frontend/src/components/builder/UnifiedStackPanel.tsx` — BasemapGroupRowWrapper + callsite

#### `BasemapGroupRowWrapperProps` interface + wrapper implementation

| Line | What's there | Action |
|------|--------------|--------|
| 231 | `onOpacityChange: (id: string, opacity: number) => void;` in `BasemapGroupRowWrapperProps` | **Remove** (wrapper exists only to render `<BasemapGroupRow>` — when the child no longer accepts it, the wrapper no longer needs to declare it) |
| 251 | `onOpacityChange,` destructure in `BasemapGroupRowWrapper()` params | **Remove** |
| 282 | `onOpacityChange={onOpacityChange}` prop passed to `<BasemapGroupRow>` | **Remove** |

#### `<BasemapGroupRowWrapper>` callsite

| Line | What's there | Action |
|------|--------------|--------|
| 780 | `onOpacityChange={() => {}} // opacity via master slider in Scene B editor` — **NOOP wired in v1; NOT the live `onOpacityChange` prop** | **Remove the prop entirely** (becomes type error after wrapper interface change). The inline comment that justified the NOOP can also be removed since the prop is gone. |

#### What stays untouched

| Line | What's there | Why leave alone |
|------|--------------|-----------------|
| 76 | `onOpacityChange: (layerId: string, opacity: number) => void;` in top-level `UnifiedStackPanelProps` | **Already known to be unused inside the panel** per comment at lines 589-594. After this task it remains in the interface for `MapBuilderPage` call-site compatibility and because `handlers.onOpacityChange` still flows through to `LayerEditorPanel`. Removing it is a separate cleanup. Per 260515-rdn §1 + 260515-sqf §1 — **leave alone.** |
| 589-594 | Comment explaining `onOpacityChange` is intentionally NOT destructured at the main panel level | **Leave alone** — comment is accurate and explains the situation cleanly. |

#### Crucial deviation from 260515-rdn/sqf shape

**The 260515-rdn/sqf precedents had `onOpacityChange={onOpacityChange}` (live prop) at the wrapper callsite.** In contrast, here at `UnifiedStackPanel.tsx:780` the wiring is `onOpacityChange={() => {}}` (NOOP). This means:
- The dead callback was *never* connected to `handleOpacityChange` for the basemap group row. The row slider was broken in TWO ways: (1) the upstream callback was NOOP, AND (2) even if it had been live, `applyLayerUpdate('basemap-group', ...)` short-circuits because no layer with that id exists (per 260515-tb3 RESEARCH §C1).
- Removing the slider also removes the NOOP — net behavior is unchanged (the NOOP did nothing, removal does nothing).
- **TypeScript safety net works identically** to the precedents: dropping the prop from `BasemapGroupRowProps` will surface the wrapper instantiation + the wrapper interface + the callsite.

### What stays untouched elsewhere

- `MapBuilderPage.tsx:230` (top-level `handlers.onOpacityChange = layers.handleOpacityChange`) — still load-bearing for `LayerEditorPanel`, sublayer rows, ChatPanel.
- `use-builder-layers.ts:944` (`onOpacityChange: handleOpacityChange` on `chatLayerActions`) — load-bearing for chat semantic dispatch.
- `FolderGroupRow.tsx`, `StackRow.tsx` — already cleaned by 260515-rdn and 260515-sqf.
- `BasemapGroupEditorScene.tsx` — sublayer slider (per-sublayer, in-flyout) untouched.
- `UnifiedStackPanel.tsx::SublayerRow` (basemap sublayer rows in expanded basemap group) — still uses `onSublayerOpacityChange`, unrelated. Untouched.

---

## 5. Frontend Path B touchpoints

### 5A. Persistence wire-up (the explicit Phase 1038 TODO)

#### Save site

`frontend/src/components/builder/hooks/use-builder-save.ts:396` — **the canonical save-payload assembly point**:

```ts
const metadataPayload: MapUpdateRequest = {
  name: localName || undefined,
  description: localDescription.trim() || null,
  notes: dockNotes.trim() || null,
  basemap_style: localBasemap,
  show_basemap_labels: showBasemapLabels,
  basemap_config: basemapConfig,           // <-- this line
  terrain_config: terrainConfig,
  ...
};
```

`basemapConfig` here is the React-state `basemapConfig` shape (`MapBasemapConfig | null` per `frontend/src/types/api.ts:20`).

**Wire-up options:**

**Option A (recommended): pass masterOpacity into `useBuilderSave`'s `SaveState` and merge it into `basemap_config` payload here.**

`SaveState` interface at `use-builder-save.ts:317-331` would gain a new field:
```ts
masterOpacity: number;
```

And the payload assembly becomes:
```ts
basemap_config: basemapConfig
  ? { ...basemapConfig, opacity: masterOpacity }
  : (masterOpacity !== 1 ? { ...DEFAULT_BASEMAP_CONFIG_SHAPE, opacity: masterOpacity } : null),
```

This is fiddly because `basemapConfig` can be `null` (when user hasn't customized basemap appearance). If user only edits master opacity (without other basemap config edits), `basemapConfig` would be `null`, and the new opacity would be lost unless we spin up a default config. The cleanest treatment: when `basemapConfig` is `null` AND `masterOpacity !== 1`, build a minimal `MapBasemapConfig` with defaults + the opacity override.

**Option B (cleaner): lift masterOpacity into `basemapConfig` state at the source.**

In `MapBuilderPage.tsx`, change the `onMasterOpacityChange` handler at line 755-761 to BOTH update `masterOpacity` AND update `layers.basemapConfig`:

```tsx
onMasterOpacityChange={(opacity) => {
  setMasterOpacity(opacity);
  const current = layers.basemapConfig ?? normalizeBasemapConfig(null, layers.showBasemapLabels);
  layers.setBasemapConfig({ ...current, opacity });
  layers.markDirty();
}}
```

This makes `basemapConfig.opacity` the single source of truth. The local `masterOpacity` state becomes a derived/cached value. **Trade-off:** the local `masterOpacity` state at `MapBuilderPage.tsx:258` becomes redundant — the value can be read from `layers.basemapConfig?.opacity ?? 1` directly.

**Recommendation: Option B with light refactor.** Eliminate the `masterOpacity` local React state entirely. Pass `layers.basemapConfig?.opacity ?? 1` into `<BasemapGroupEditorScene masterOpacity={...} />` and update via `layers.setBasemapConfig({ ...current, opacity })`. This avoids state-duplication bugs (cf. the freshLayerId B-01 race in v1009).

**Trade-off the planner must decide:** Option B touches more lines (kill `masterOpacity` local state, rewire `basemapGroup` memo at line 275 to read from `basemapConfig`) but eliminates a future drift class. Option A leaves the local state in place but adds a sync coupling. **Planner should consult the user; both are correct, but Option B is the smaller surface AFTER the refactor.**

#### Load site

`frontend/src/components/builder/hooks/use-builder-layers.ts:120` — the canonical initializer:

```ts
useEffect(() => {
  if (mapData && !initializedRef.current) {
    setLocalLayers(mapData.layers ?? []);
    savedLayerBaselineRef.current = mapData.layers ?? [];
    setLocalBasemap(resolveBasemapId(mapData.basemap_style || 'positron'));
    setShowBasemapLabels(mapData.show_basemap_labels ?? true);
    setBasemapConfig(mapData.basemap_config ?? null);   // <-- this line
    setLocalTerrainConfig(mapData.terrain_config ?? null);
    ...
  }
}, [mapData]);
```

`setBasemapConfig(mapData.basemap_config ?? null)` already does the right thing — when `opacity` is present in the loaded payload, it becomes part of the React `basemapConfig` state. The new `MapBasemapConfig` TS interface (see §5C) will include `opacity` as optional, so the field flows in cleanly.

**Important correction to CONTEXT.md:** CONTEXT.md says "Replace the load-side `setMasterOpacity(1)` at line 469 with `setMasterOpacity(mapData.basemap_config?.opacity ?? 1)`." Line 469 is INSIDE `handleResetBasemapAppearance` — it fires on user-initiated "Reset appearance" action, NOT on map load. The correct load-side seeding lives at `use-builder-layers.ts:120`, NOT at `MapBuilderPage.tsx:469`. **Planner must use the corrected location.**

- If Option B (above) is chosen: load is automatic (`basemapConfig.opacity` flows through `setBasemapConfig`). No code change in `use-builder-layers.ts:120` needed beyond updating the TS interface so opacity is typed.
- If Option A is chosen: add `setMasterOpacity(mapData.basemap_config?.opacity ?? 1)` inside the same useEffect after `setBasemapConfig(...)`. The line 469 reset stays at `setMasterOpacity(1)` (reset-to-default semantics — user explicitly clicked "Reset appearance" — but per CONTEXT.md spec the new reset also clears `basemapConfig` to null, so both line up).

#### TypeScript type update

`frontend/src/types/api.ts:20-27`:

```ts
export interface MapBasemapConfig {
  label_mode: MapBasemapVisibilityMode;
  road_visibility: MapBasemapVisibilityMode;
  boundary_visibility: MapBasemapVisibilityMode;
  building_visibility: boolean;
  land_water_tone: MapBasemapLandWaterTone;
  relief_contrast?: MapBasemapReliefContrast | null;
}
```

**Add:** `opacity?: number;` (optional, defaults to 1.0 server-side). Position: after `relief_contrast` (mirrors backend Pydantic field order).

### 5B. Runtime application — **PLANNER-BLOCKING CAVEAT**

**Finding (HIGH confidence):** `masterOpacity` is currently NOT applied to the rendered MapLibre basemap style at all. Per `grep -rn "masterOpacity" frontend/src/`:

| File | Line | Usage |
|------|------|-------|
| `MapBuilderPage.tsx` | 258 | `const [masterOpacity, setMasterOpacity] = useState(1);` (declaration) |
| `MapBuilderPage.tsx` | 275 | `opacity: masterOpacity,` (read into `basemapGroup.opacity` memo) |
| `MapBuilderPage.tsx` | 315 | dependency in `basemapGroup` memo |
| `MapBuilderPage.tsx` | 750 | `masterOpacity={basemapGroup.opacity}` (prop to editor scene — used only to render slider value) |
| `BasemapGroupEditorScene.tsx` | 27, 65, 226, 229, 230, 231, 237 | renders the slider (controlled `value={[masterOpacity]}`) |
| `layer-adapters/shared.ts` | 76, 80, 86, 94, 96, 144, 150 | accepts a `masterOpacity` arg in opacity-blending helpers — but called only by per-layer adapters (`fill-adapter.ts`, etc.) which pass the **per-layer `layer.opacity` field**, not the basemap-group master opacity. **NAMING COLLISION** — these `masterOpacity` parameters refer to a layer's own opacity multiplier, not the basemap-group concept. Unrelated. |
| `LegendWidget.tsx` | 22, 40 | same naming-collision pattern (per-layer opacity, not basemap-group master) |

**`frontend/src/lib/basemap-utils.ts::applyBasemapConfigToStyle`** (lines 342-354) — the function that maps `MapBasemapConfig` → MapLibre paint mutations — reads `label_mode`, `road_visibility`, `boundary_visibility`, `building_visibility`, `land_water_tone`, and `relief_contrast`. It does NOT read `opacity`. The four `*-opacity` references in `basemap-utils.ts` (lines 317, 318, 325, 333, 334) are all from `applyProminence` (subtle-mode for road/boundary/label sublayers), not master opacity.

**`frontend/src/components/builder/map-sync.ts::applyBasemapConfigToMap`** (lines 216-260) — invoked from `BuilderMap.tsx:739` — calls `applyBasemapConfigToStyle` under the hood. Same gap.

**260515-tb3 RESEARCH §C2 actually said:** "Master slider DOES move runtime (1 → 0.55 in test) ... Visual map effect: **not screenshot-checked**, but Phase-1038 TODO + source flow indicate runtime visual change should occur via setMasterOpacity → BasemapGroupEditorScene re-render". That assumption was **wrong**. Source-level evidence proves the slider value moves in the controlled-component sense (Radix updates `aria-valuenow`), but the new value never reaches a `map.setPaintProperty(...)` call. The basemap visually does not change as the user drags the master opacity slider.

**Implications for this task:**

1. **CRITICAL — the user-visible "master opacity" slider in BasemapGroupEditorScene currently does NOTHING visually.** Even before Path B persistence work, the runtime application gap is a real bug.

2. **Path B as written closes the PERSISTENCE half but not the RUNTIME-APPLICATION half.** A user can drag the master slider, click Save, reload — and the persisted `0.55` value will load back and re-render the slider at `0.55`. The basemap still won't visually dim. The user will perceive the save/reload as functional but the opacity itself as broken.

3. **Two options the planner must choose between:**
   - **(B-narrow):** Ship Path B as scoped — persistence only, **add a TODO comment** at `applyBasemapConfigToStyle` and `applyBasemapConfigToMap` noting the runtime gap, and **defer runtime application to a follow-up quick task**. Closes the schema + wire-up debt cleanly. Honest about the residual gap. Aligns with CONTEXT.md's "Claude's discretion ... if propagation would touch many code paths or risks visual regression, narrow Path B to persistence only and defer style-JSON propagation to a Phase-1038 follow-up" (CONTEXT.md "Style JSON consumer" decision — same reasoning applies to the frontend runtime).
   - **(B-wide):** Bundle runtime application — add a code path in `applyBasemapConfigToMap` that walks basemap-only layers and applies `raster-opacity` (raster basemap layers) / `fill-opacity` / `line-opacity` / `text-opacity` (vector basemap layers) based on `config.opacity`. Adds ~30-50 LOC plus the question "should this be a paint mutation or a CSS map-container opacity?" plus a vitest extension to `BuilderMap.unit.test.ts` that covers the new code path.
   - **Recommendation: B-narrow.** Persistence is what the Phase-1038 TODO actually blocks, and the runtime gap is a separable bug (it predates Path B and would still exist after Path A alone). Keep this task atomic; track runtime application as a clean follow-up. **Tell the user explicitly** before finalizing — they may want the visual fix in this task even though it's larger.

4. **Manual smoke test (CONTEXT.md "Verification gates"):** the script says "drag master opacity 1 → 0.55 → save button transitions to 'Unsaved' → save (⌘S or click) → reload page → master opacity slider re-renders at 0.55". This is achievable with B-narrow. The script does NOT say "verify the basemap visually dims" — good, because B-narrow does not deliver that. Planner should leave that out of the smoke checklist OR add an explicit "the basemap is NOT expected to visually dim; this is a known runtime-application gap deferred to follow-up" note.

### 5C. The `BasemapGroupInfo` shape (used by `<BasemapGroupRowWrapper>`)

Verified at `UnifiedStackPanel.tsx:222-236` and the `group` prop type — `BasemapGroupInfo` is defined elsewhere in the file and includes an `opacity: number` field that originates from `basemapGroup.opacity` in `MapBuilderPage.tsx:275`. After Path A removes the slider from `BasemapGroupRow`, this `opacity` field is no longer rendered anywhere by the row. **BUT** the `opacity` field on `BasemapGroupInfo` is still consumed by the master-opacity slider in `BasemapGroupEditorScene` (via `masterOpacity={basemapGroup.opacity}` at `MapBuilderPage.tsx:750`). **Leave `BasemapGroupInfo.opacity` alone** — it remains load-bearing for the surviving canonical control.

If the planner chooses Option B (kill `masterOpacity` local state and derive from `layers.basemapConfig.opacity`), `basemapGroup.opacity` at line 275 becomes:
```ts
opacity: layers.basemapConfig?.opacity ?? 1,
```

…and the `masterOpacity` dependency in the memo (line 315) is replaced by `layers.basemapConfig`.

---

## 6. Side-finding: `applyLayerUpdate` dirty-gate

### `frontend/src/components/builder/hooks/use-layer-map-sync.ts:41-61`

Current code:
```ts
const applyLayerUpdate = useCallback(
  (layerId: string, updater: LayerUpdater, applyFn?: LayerSideEffect) => {
    let updated: MapLayerResponse | undefined;
    setLocalLayers((prev) =>
      prev.map((l) => {
        if (l.id !== layerId) return l;
        const next = updater(l);
        updated = next;
        return next;
      }),
    );
    setHasUnsavedChanges(true);          // <-- unconditional

    if (!applyFn) return;
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;
    if (!updated) return;
    applyFn(map, updated);
  },
  [setLocalLayers, setHasUnsavedChanges, mapInstanceRef],
);
```

Proposed change: move `setHasUnsavedChanges(true)` inside an `if (updated)` block:
```ts
if (updated) setHasUnsavedChanges(true);
```

### Safety audit of `applyLayerUpdate` callers

All callers are internal to `use-layer-map-sync.ts`. Verified via `grep -n "applyLayerUpdate(" frontend/src/components/builder/hooks/use-layer-map-sync.ts`:

| Caller | Line | `layerId` source | Real-id guarantee? |
|--------|------|------------------|--------------------|
| `handleToggleVisibility` | 67 | function parameter | YES — called by per-layer eye buttons + bulk-visibility ops + LayerEditorPanel; always a real layer id |
| `handlePaintChange` | 92 | function parameter | YES — called by paint editors keyed to a specific layer |
| `handleStyleConfigChange` | 126 | function parameter | YES — called by style/render-mode editors keyed to a specific layer |
| `handleOpacityChange` | 187 | function parameter | YES for the LayerEditorPanel Visibility slider + bulk-opacity (real ids); **NO for the dead `BasemapGroupRow` row slider that fed `"basemap-group"` synthetic id** (per 260515-tb3 RESEARCH §C1) — but after Path A, that broken caller is gone |
| `handleLayoutChange` | 243 | function parameter | YES — called by layout editors keyed to a specific layer |
| `handleFilterChange` | 305 | function parameter | YES — called by FilterPanel keyed to a specific layer |
| `handleLabelChange` | 354 | function parameter | YES — called by LabelEditor keyed to a specific layer |
| `handlePopupChange` | 399 | function parameter | YES — called by PopupEditor keyed to a specific layer |

**Conclusion: ALL 8 callers operate on real layer ids in normal use.** The dirty-gate change is safe. The behavior change is exclusively: stop falsely marking dirty when the caller passes an unknown id — which only happened via the now-removed BasemapGroupRow row slider bug.

**No caller relies on the unconditional dirty-set as a workaround.** None of the 8 callers do any setup work that depends on `setHasUnsavedChanges(true)` firing before the layer lookup completes — they just call `applyLayerUpdate` and trust the side effect.

### Test target

**No existing `use-layer-map-sync.test.ts` file exists** (verified via `ls frontend/src/components/builder/hooks/__tests__/`). The closest existing test is `use-builder-layers.test.ts:201-212` (`handleOpacityChange updates opacity and marks dirty`) which exercises the chain via `use-builder-layers`. That hook delegates to `useLayerMapSync`, so the dirty-gate test can live in `use-builder-layers.test.ts` alongside it:

```ts
it('handleOpacityChange does NOT mark dirty for nonexistent layer id', () => {
  const layer = makeMockLayer();
  const mapData = makeMapData([layer]);
  const { result } = renderBuilderLayers(mapData);

  act(() => {
    result.current.handleOpacityChange('nonexistent-id', 0.5);
  });

  expect(result.current.hasUnsavedChanges).toBe(false);
  expect(result.current.localLayers[0].opacity).toBe(1);  // unchanged
});
```

Alternative: create a new `use-layer-map-sync.test.ts` and exercise the hook directly. Marginal — extending the existing file is the smaller diff.

---

## 7. Frontend test touchpoints

### `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx`

| Line(s) | What's there | Action |
|---------|--------------|--------|
| 59 | `opacity: 1,` in `defaultProps()` factory | **Remove** (tracks `opacity` prop removal at BasemapGroupRow.tsx:25) |
| 67 | `onOpacityChange: vi.fn(),` in `defaultProps()` factory | **Remove** (tracks `onOpacityChange` prop removal at BasemapGroupRow.tsx:36) |
| 170-181 | `it('Test 9: opacity slider calls onOpacityChange(groupId, value) and stopPropagation prevents row click', ...)` — entire test block | **Delete entire test** (the slider is gone). The test asserts the slider exists via `screen.getByRole('slider')`; with the slider removed, the assertion would fail. |

### Other test files — checked, no BasemapGroupRow row-slider assertions to update

| File | Status |
|------|--------|
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` | Passes `onOpacityChange: vi.fn()` to UnifiedStackPanel top-level — **leave alone** (still needed by top-level prop; group rows + LayerEditorPanel still consume it indirectly through the parent surface) |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.multi-select.test.tsx` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` | Already cleaned by 260515-sqf. **Leave alone.** |
| `frontend/src/components/builder/__tests__/StackRow.test.tsx` | Already cleaned by 260515-rdn. **Leave alone.** |
| `frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx` | Tests the IN-flyout sublayer + master sliders. **Leave alone.** |
| `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx`, `LayerStyleEditor.test.tsx`, etc. | Test in-flyout controls. **Leave alone.** |

### Round-trip test for masterOpacity persistence

**Recommendation:** EXTEND `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts:368-417` rather than write a new file. That test (`it('omits layers when only metadata changes', ...)` — line range that includes the basemap_config block) already exercises a PUT-with-basemap_config round-trip with the exact same fixture shape we need.

Pattern to add (new test, immediately after the existing one):
```ts
it('persists basemap_config.opacity when masterOpacity changes', async () => {
  const layer = makeLayer();
  let state = makeSaveState({ localLayers: [layer] });
  const { result, rerender } = renderHook(() => useBuilderSave(state));

  state = makeSaveState({
    localLayers: [layer],
    basemapConfig: {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      relief_contrast: null,
      opacity: 0.55,                    // <-- the new field
    },
    hasUnsavedChanges: true,
  });
  rerender();

  await act(async () => {
    await result.current.handleSave();
  });

  expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
    expect.objectContaining({
      data: expect.objectContaining({
        basemap_config: expect.objectContaining({ opacity: 0.55 }),
      }),
    }),
  );
});
```

The TS interface update in §5C (adding `opacity?: number`) is a prerequisite for this test to typecheck.

### Dirty-gate test for `applyLayerUpdate`

See §6 — add to `use-builder-layers.test.ts` adjacent to the existing `handleOpacityChange` test at line 201.

---

## 8. i18n touchpoints — CRITICAL CAVEAT (proactively preserved in CONTEXT.md)

CONTEXT.md already encodes the right decision after the 260515-rdn precedent: **DO NOT delete the `stackRow.opacitySlider` i18n key.** This research confirms the consumer count is 2 today → 1 after this task (not 2 → 0).

### Current consumers of `t('stackRow.opacitySlider', ...)`

`grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` returns 2 matches **today**:

| Consumer | File:Line | Status after this task |
|----------|-----------|------------------------|
| Basemap-group row slider (this task removes it) | `BasemapGroupRow.tsx:189` | **Removed** |
| Basemap-editor sublayer slider (OUT-OF-SCOPE) | `BasemapGroupEditorScene.tsx:196` | **Still uses the key** |

After this task: `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` MUST return exactly **1** match. (Was 4 before 260515-rdn → 3 after 260515-rdn → 2 today after 260515-sqf → 1 after this task.)

### Locale files — DO NOT TOUCH

| File | Line | Content |
|------|------|---------|
| `frontend/src/i18n/locales/en/builder.json` | 814 | `"opacitySlider": "Opacity for {{name}}",` |
| `frontend/src/i18n/locales/de/builder.json` | 814 | `"opacitySlider": "Deckkraft für {{name}}",` |
| `frontend/src/i18n/locales/es/builder.json` | 814 | `"opacitySlider": "Opacidad para {{name}}",` |
| `frontend/src/i18n/locales/fr/builder.json` | 814 | `"opacitySlider": "Opacité pour {{name}}",` |

All four files stay byte-identical. The key remains in active use by `BasemapGroupEditorScene.tsx`.

**Why this is still flagged as "CRITICAL":** the precondition has narrowed twice already (4 → 3 → 2 today). It's now at the floor of "one remaining consumer". The planner must hold the line — *do not* let an executor "tidy up" the key on the grounds that "BasemapGroupRow no longer uses it" or that "it's only used by one sibling now". The sibling consumer is permanent (sublayer sliders are not in scope for removal).

---

## 9. Sketch / planning doc touchpoints

### `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`

The doc was updated twice already (260515-rdn + 260515-sqf). This task narrows it a third time.

| Line(s) | What's there now | Action |
|---------|------------------|--------|
| 34–44 | Forward note paragraph: `...basemap group rows and basemap-editor sublayer rows retain their own opacity sliders ... the HTML example for the group row below illustrates a basemap-group row; a user-folder-group row uses the same anatomy but without the .opacity range input.` | **Narrow** — change "basemap group rows and basemap-editor sublayer rows" to "**only basemap-editor sublayer rows** (inside the BasemapGroupEditorScene flyout)". Adjust the group-row HTML example reference: it no longer illustrates a basemap-group row (basemap groups no longer have sliders). Proposed wording in callout below. |
| 163–178 | HTML example "A group row (basemap or user folder)" with `<input class="opacity">` on line 172 and the helper comment on line 171 `<!-- basemap-group row; user-folder-group row has no .opacity input as of 260515-sqf -->` | **AMBIGUOUS — Claude's discretion.** Two options: **(a)** Remove the `<input class="opacity">` line + the line-171 comment (basemap groups no longer have a slider either, so the entire example is now a misrepresentation). The example becomes a clean 6-column group row identical to a folder group row. **(b)** Keep the `<input class="opacity">` line as illustrative of the basemap-editor SUBLAYER row (move it down into a new "Basemap sublayer row (inside the editor flyout)" example) and remove from the main group-row example. **Recommended: (a)** — keep the diff small and the example consistent with the new reality. Add an inline HTML comment: `<!-- Note: no per-row opacity slider on group rows as of 260516-9g9. Per-sublayer opacity lives in the BasemapGroupEditorScene flyout only. -->`. |
| 144 | `.group-children .row { grid-template-columns: 16px 14px 22px 22px 1fr 22px; padding: 6px 8px 6px 4px; }` (already 6-col) | **No change** — already correct from 260515-rdn. |
| 21–23 | Row anatomy diagram already shows 6 columns (no `[opacity]` token) | **No change** — already correct from 260515-rdn. |

### Proposed forward-note rewrite (replaces current lines 34–44)

```
> **Note (2026-05-16, quick tasks 260515-rdn + 260515-sqf + 260516-9g9):** The
> per-row opacity slider was removed in three sweeps — first from non-group
> rows (260515-rdn), then from user-folder group rows (260515-sqf), and finally
> from basemap group rows (260516-9g9 — also shipped master-opacity persistence
> via `basemap_config.opacity`). Opacity is now edited exclusively in the
> LayerEditorPanel Visibility section (see `layer-editor-flyout.md`) for both
> loose layers and user-folder groups, and in the BasemapGroupEditorScene
> "Master opacity" slider for basemap groups. The dedicated 60px slider column
> was collapsed across all three row variants; the row template is six columns:
> `16px 14px 22px 22px 1fr 22px`. **Only basemap-editor SUBLAYER rows** (the
> per-sublayer rows inside the BasemapGroupEditorScene flyout) retain their
> own per-row opacity sliders — every stack-list row (loose, folder group,
> basemap group) is slider-free.
```

### `.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md`

**Not changed** — this is the surviving canonical control's spec. The new master-opacity persistence is a wire-up concern, not a spec change for the flyout itself.

---

## 10. Public-API spot-check

### Backend `BasemapConfig` is exposed in OpenAPI

Per 260515-tb3 RESEARCH §C2, the backend `BasemapConfig` schema appears in `openapi.json`. Adding the `opacity` field will appear in the regenerated OpenAPI document. Consumer impact:

| Consumer | Location | Impact | Action |
|----------|----------|--------|--------|
| Python SDK | `sdks/python/geolens/models/basemap_config.py` | Will be regenerated to include `opacity: float \| Unset` field | **No edit required in this task** — regen runs separately. Existing Python SDK consumers continue to work (omitting `opacity` defaults to 1.0 server-side). |
| TypeScript SDK | `sdks/typescript/src/client/types.gen.ts:737` | Will be regenerated to include `opacity?: number;` field | **No edit required in this task** — regen runs separately. Existing TS SDK consumers continue to work. |
| Frontend (`frontend/src/types/api.ts:20-27`) | `MapBasemapConfig` interface | Hand-maintained, NOT auto-generated. **Must be updated in this task per §5C** to add `opacity?: number;`. |
| `geolens-enterprise` repo | — | `grep -rn "BasemapConfig\|basemap_config" /Users/ishiland/Code/geolens-enterprise/` → **zero matches**. Enterprise overlay does not reference BasemapConfig. **No action.** |
| `getgeolens.com` repo | — | Marketing site; does not import frontend types. **No action.** |

### Schema change is backwards compatible

- Old clients sending `basemap_config: { label_mode: "full", ... }` (without opacity) — Pydantic injects default `opacity=1.0`. Stored as `{..., "opacity": 1.0}`. Round-trip works.
- Old clients reading `basemap_config` from `MapResponse` — receive the new opacity field. If they ignore unknown fields (typical client behavior), no breakage. If they whitelist fields strictly, they ignore opacity. Either way, no error.
- New clients sending opacity — accepted and persisted.
- Edge case: an existing Python SDK pinned to a version BEFORE the regen — sending `BasemapConfig(...)` without opacity emits a payload without the key. Backend defaults to 1.0. Reading a response with the key requires the new SDK version, OR the older SDK silently drops the field (depends on `attrs.define` behavior with unknown attrs — Python SDK uses `UNSET` sentinel pattern, which gracefully accepts unknown attributes).

**No regen blocker. SDK regeneration is recommended in a future sweep but is not gating for this task.**

---

## 11. Estimated blast radius

### File count
- **Files modified:** 9
  1. `backend/app/modules/catalog/maps/schemas.py` (add 1 field)
  2. `backend/tests/test_maps.py` (extend fixture + add Pydantic tests + optionally add focused round-trip)
  3. `frontend/src/components/builder/BasemapGroupRow.tsx` (remove slider + import + props + grid)
  4. `frontend/src/components/builder/UnifiedStackPanel.tsx` (remove BasemapGroupRowWrapper plumbing + NOOP callsite)
  5. `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` (drop 2 prop defaults + delete 1 test)
  6. `frontend/src/types/api.ts` (add `opacity?: number;` to `MapBasemapConfig`)
  7. `frontend/src/components/builder/hooks/use-builder-save.ts` OR `frontend/src/pages/MapBuilderPage.tsx` (wire opacity into save — depends on Option A vs B in §5A)
  8. `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (dirty-gate edit)
  9. `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts` (dirty-gate test) + `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` (round-trip test)
  10. `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` (forward note + HTML example)

That's actually 10 files counting both test files. CONTEXT.md estimated "~+30-50 LOC" — see breakdown below.

### LOC delta (estimate)

| File | Removed | Added | Net |
|------|---------|-------|-----|
| `schemas.py` | 0 | ~3 lines (the new Field) | **+3** |
| `test_maps.py` | 0 | ~30 lines (4 new Pydantic tests + 1 focused round-trip test + fixture update +1 line) | **+30** |
| `BasemapGroupRow.tsx` | 1 import + 2 interface lines (`opacity`, `onOpacityChange`) + 2 destructure lines + 1 local + 23-line Cell-6 block + 1 comment edit | ~1 line (grid template edit, net 0) | **−29** |
| `UnifiedStackPanel.tsx` | 1 interface line + 1 destructure + 1 `<BasemapGroupRow>` prop + 1 NOOP at callsite + inline comment | 0 | **−5** |
| `BasemapGroupRow.test.tsx` | 2 defaultProps lines + 12-line Test 9 block | 0 | **−14** |
| `types/api.ts` | 0 | 1 line | **+1** |
| `use-builder-save.ts` OR `MapBuilderPage.tsx` | (depends on Option A vs B; B is leaner) | Option B: ~5 lines net (kill `masterOpacity` state, derive from basemapConfig) | **+3 to +8** |
| `use-layer-map-sync.ts` | 0 | 1 line (move inside `if`) | **+1** |
| `use-builder-layers.test.ts` | 0 | ~12 lines (dirty-gate test) | **+12** |
| `use-builder-save.test.ts` | 0 | ~30 lines (round-trip test) | **+30** |
| `layer-rows-and-groups.md` | ~11 lines (old forward note + HTML opacity input + comment) | ~12 lines (new forward note + HTML comment) | **+1** |
| **Total** | **~70** | **~95** | **+25 LOC** |

Within CONTEXT.md's "~+30-50 LOC" estimate range, on the low end.

### Risk

- **LOW-MEDIUM.** TypeScript safety net catches missing edits in `UnifiedStackPanel.tsx` (the line 282 + 780 edits). Pydantic safety net catches missing Optional handling in the TS types. The two largest risks are:
  - **The Option A vs B decision in §5A** — needs explicit user/planner choice. Bundling Option A is faster but locks in state-duplication. Option B is slightly larger but cleaner.
  - **The runtime-application gap in §5B** — if not surfaced to the user before execution, the user may file a follow-up bug claiming "Path B didn't work" because the basemap doesn't visually dim despite the slider value persisting.
- **One sharp edge — proactively neutralized by CONTEXT.md:** the i18n key STAYS (CONTEXT.md got it right after the 260515-rdn precedent). §8 confirms the precondition is now at the floor (1 remaining consumer). Hold the line.
- **One CONTEXT.md correction:** load-side seeding lives at `use-builder-layers.ts:120`, NOT `MapBuilderPage.tsx:469`. See §5A.

### Verification checkpoints for the executor

1. `cd backend && uv run pytest tests/test_maps.py -k basemap` — must pass (existing 5 tests + new 4-5 Pydantic + new 1 round-trip = ~10 passing). **CONTEXT.md's `tests/test_schemas.py` path does not exist; drop it.**
2. `cd backend && uv run pytest tests/test_maps_style_json.py -k basemap` — must pass (export/import round-trip with opacity).
3. `cd frontend && pnpm typecheck` — must pass (TS safety net for §4 + §5 wiring + §5C interface change).
4. `cd frontend && pnpm vitest run src/components/builder/__tests__/BasemapGroupRow.test.tsx` — must pass; baseline test count minus 1 (Test 9 removed). Net: BasemapGroupRow.test.tsx goes from N tests to N−1 tests.
5. `cd frontend && pnpm vitest run src/components/builder/__tests__ src/components/builder/hooks/__tests__` — all green; dirty-gate test passes; round-trip test passes.
6. `grep -n "onOpacityChange" frontend/src/components/builder/BasemapGroupRow.tsx` — returns `0`.
7. `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` — returns exactly `1` (BasemapGroupEditorScene.tsx:196).
8. `grep -n '"opacitySlider"' frontend/src/i18n/locales/en/builder.json frontend/src/i18n/locales/de/builder.json frontend/src/i18n/locales/es/builder.json frontend/src/i18n/locales/fr/builder.json` — returns `4` (one per locale).
9. Manual smoke per CONTEXT.md (live Playwright if available — per `feedback_playwright_mcp_self_verify`): slider 1 → 0.55 → save dirty → save → reload → slider re-renders at 0.55. **DO NOT assert visual basemap dim** (see §5B).

---

## 12. CRITICAL CAVEATS

### CAVEAT-1 (HIGH): Runtime application gap

Per §5B: **`masterOpacity` is currently NOT applied to the rendered MapLibre basemap style.** The slider value moves in the controlled-component sense but never reaches `map.setPaintProperty(...)`. Path B as scoped closes the PERSISTENCE half but not the RUNTIME-APPLICATION half. The user-visible end state with this task alone: master opacity persists and reloads correctly, but the basemap still does not visually dim as the slider moves.

**Planner action:** Surface this to the user before finalizing the plan. Choose between B-narrow (persistence only, defer runtime to follow-up) and B-wide (bundle runtime application). RECOMMENDED: B-narrow.

### CAVEAT-2 (HIGH): CONTEXT.md load-side line is wrong

Per §5A: CONTEXT.md says "Replace the load-side `setMasterOpacity(1)` at line 469 with `setMasterOpacity(mapData.basemap_config?.opacity ?? 1)`." Line 469 is INSIDE `handleResetBasemapAppearance` (a user-initiated action), NOT the map-load initializer. The correct load-side seeding location is `frontend/src/components/builder/hooks/use-builder-layers.ts:120`. Planner must use the corrected location.

### CAVEAT-3 (HIGH): CONTEXT.md test path is wrong

Per §2: CONTEXT.md's verification gate `cd backend && uv run pytest tests/test_maps.py tests/test_schemas.py -k basemap` references `tests/test_schemas.py` which **does not exist**. Backend test layout uses per-domain schema files (`test_advanced_sharing_schema.py`, `test_commit_request_schemas.py`, etc.). Planner should put new BasemapConfig Pydantic tests in `test_maps.py` (alongside existing schema-and-integration mix for the maps domain) and drop the non-existent path from the verification command.

### CAVEAT-4 (MEDIUM): Decision between Option A and Option B for state architecture

Per §5A: there are two viable ways to wire master-opacity persistence. Option B (lift opacity into `basemapConfig` state, eliminate local `masterOpacity` React state) is the cleaner long-term shape but requires the planner to explicitly choose it over Option A (keep local state, sync to payload at save). CONTEXT.md does not specify. **The planner should pick Option B** and document the choice, OR explicitly ask the user.

### CAVEAT-5 (LOW): UnifiedStackPanel callsite is already NOOP, not live

Per §4: `UnifiedStackPanel.tsx:780` already wires `onOpacityChange={() => {}}` (NOOP) to the BasemapGroupRowWrapper. Unlike the 260515-rdn/sqf precedents where the callsite passed the live `onOpacityChange` prop. Removal is still mechanically equivalent but the executor should not be surprised by the inline NOOP — it's been dead code from before this task.

### CAVEAT-6 (LOW): CONTEXT.md "frontend tests" gate path overlaps the BasemapGroupRow.test.tsx + the dirty-gate target

CONTEXT.md's gate command:
```
cd frontend && ./node_modules/.bin/vitest run src/components/builder/__tests__ src/pages/__tests__ src/components/builder/hooks/__tests__
```
This covers BOTH BasemapGroupRow.test.tsx AND the hook test for the dirty-gate AND the round-trip test in use-builder-save.test.ts. Good — no gap. (Just noting the gate command is correctly scoped.)

---

## Sources

All findings verified directly against the working-tree files; no web sources needed.

- `rg -n "onOpacityChange"` over `frontend/src/components/builder/BasemapGroupRow.tsx` + `UnifiedStackPanel.tsx`
- `rg -n "stackRow\.opacitySlider"` over `frontend/src/components/builder/`
- `rg -n "masterOpacity\|master_opacity"` over `frontend/src/` and `backend/`
- `rg -n "applyLayerUpdate"` over `frontend/src/components/builder/hooks/`
- `rg -n "BasemapConfig\b"` over `backend/app/` and `backend/tests/`
- `rg -n "basemap_config"` over `frontend/src/`, `backend/alembic/`, `sdks/`
- `grep -n` audits on key files for line-level verification
- Direct read of: `schemas.py:1-758`, `style_json.py:1-1244`, `BasemapGroupRow.tsx:1-241`, `BasemapGroupEditorScene.tsx:1-268`, `UnifiedStackPanel.tsx` (lines 220-300, 585-595, 765-790), `MapBuilderPage.tsx` (lines 240-340, 440-480, 740-810), `use-layer-map-sync.ts:1-415`, `use-builder-layers.ts` (lines 60-130, 930-1009), `use-builder-save.ts` (lines 310-420), `models.py:75-100`, `alembic/versions/0011_map_basemap_config.py`, `basemap-utils.ts:320-400`, `map-sync.ts:200-270`, `types/api.ts:15-30`, `BasemapGroupRow.test.tsx:1-260`, `test_maps.py:30-50, 220-250, 490-535`, `layer-rows-and-groups.md:1-200`
- Predecessors: `260515-tb3-RESEARCH.md`, `260515-rdn-RESEARCH.md`, `260515-rdn-PLAN.md`, `260515-sqf-RESEARCH.md`, `260516-9g9-CONTEXT.md`
- Spot-checked `~/Code/geolens-enterprise/` for `BasemapConfig` + `BasemapGroupRow` references — zero matches
- Confirmed `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` does not exist; closest hook test is `use-builder-layers.test.ts:201-212`
- Confirmed `backend/tests/test_schemas.py` does not exist (per `ls backend/tests/`)
- Confirmed generated SDKs at `sdks/python/geolens/models/basemap_config.py` (attrs-based) and `sdks/typescript/src/client/types.gen.ts:737` (TS interface) — both will pick up the new opacity field on regeneration
