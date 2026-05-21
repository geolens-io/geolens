---
phase: 260425-oxh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py
  - backend/app/modules/catalog/maps/models.py
  - backend/app/modules/catalog/maps/schemas.py
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/router.py
  - frontend/src/types/api.ts
  - frontend/src/lib/popup-template.ts
  - frontend/src/components/builder/PopupConfigEditor.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/map/FeaturePopup.tsx
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx
  - frontend/src/lib/__tests__/popup-template.test.ts
autonomous: true
requirements: [oxh-popup-toggle, oxh-popup-template, oxh-visible-fields, oxh-validation]

must_haves:
  truths:
    - "User can open the new 'Popup' tab in the layer editor for a vector layer"
    - "User can toggle popups on/off for a layer; off makes clicks on that layer's features show no popup"
    - "User can type a template like '{city}, {state}' and the substituted result appears as a title above the existing FeaturePopup property table"
    - "User can pick a sortable allowlist of visible fields; only those fields show, in the order specified; empty list shows no rows; null shows all (current default)"
    - "Live validation highlights unknown {placeholders} as the user types (debounced ~250ms); save is blocked when invalid"
    - "popup_config persists end-to-end (DB column → API response → frontend state → reload restores)"
    - "Other layers' popup behavior is unchanged when one layer has popups disabled"
  artifacts:
    - path: "backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py"
      provides: "Alembic migration adding popup_config JSONB NULL to catalog.map_layers"
      contains: "add_column"
    - path: "backend/app/modules/catalog/maps/models.py"
      provides: "MapLayer.popup_config Mapped[dict | None]"
      contains: "popup_config"
    - path: "backend/app/modules/catalog/maps/schemas.py"
      provides: "popup_config field on MapLayerInput, MapLayerResponse, SharedLayerResponse"
      contains: "popup_config"
    - path: "frontend/src/types/api.ts"
      provides: "PopupConfig interface + popup_config field on MapLayerResponse/Input/SharedLayerResponse"
      contains: "PopupConfig"
    - path: "frontend/src/lib/popup-template.ts"
      provides: "extractPlaceholders, validatePlaceholders, substitutePopupTemplate utilities"
      exports: ["extractPlaceholders", "validatePlaceholders", "substitutePopupTemplate"]
    - path: "frontend/src/components/builder/PopupConfigEditor.tsx"
      provides: "Popup config editor: enable toggle, expression textarea, sortable visible-fields picker, live validation"
      min_lines: 100
    - path: "frontend/src/components/builder/LayerEditorPanel.tsx"
      provides: "Adds 'popup' as a 4th tab; tab union extended; renders PopupConfigEditor for that tab"
      contains: "PopupConfigEditor"
    - path: "frontend/src/components/map/FeaturePopup.tsx"
      provides: "FeatureInfo extended with optional title + visibleFields; renders title above table; respects ordered allowlist"
      contains: "title"
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "Click handler filters hits by popup_config.enabled !== false; substitutes title + passes visibleFields per feature"
      contains: "popup_config"
  key_links:
    - from: "frontend/src/components/builder/PopupConfigEditor.tsx"
      to: "frontend/src/lib/popup-template.ts"
      via: "extractPlaceholders + validatePlaceholders for live + on-save validation"
      pattern: "extractPlaceholders|validatePlaceholders"
    - from: "frontend/src/components/builder/LayerEditorPanel.tsx"
      to: "frontend/src/components/builder/PopupConfigEditor.tsx"
      via: "rendered when activeTab === 'popup'"
      pattern: "PopupConfigEditor"
    - from: "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
      to: "frontend/src/types/api.ts (PopupConfig)"
      via: "handlePopupChange writes popup_config via applyLayerUpdate (no map side-effect)"
      pattern: "handlePopupChange|popup_config"
    - from: "frontend/src/components/builder/BuilderMap.tsx"
      to: "frontend/src/components/map/FeaturePopup.tsx"
      via: "passes substituted title + visibleFields per feature; filters hits by enabled flag"
      pattern: "popup_config\\?\\.\\s*enabled|substitutePopupTemplate"
    - from: "backend/app/modules/catalog/maps/service.py (3 sites: add/duplicate/_build_shared_layer_dict)"
      to: "backend/app/modules/catalog/maps/models.py (MapLayer.popup_config)"
      via: "popup_config persisted on MapLayer create + copied on fork + included in shared response"
      pattern: "popup_config"
---

<objective>
Add per-layer popup configuration to the Map Builder: enable/disable toggle, template-string expression with `{column_name}` placeholders, sortable visible-fields allowlist, and validation against the layer's known column keys. Mirror the existing `label_config` pattern end-to-end (JSONB column, Pydantic `dict | None`, response field, frontend type, sidebar editor tab, hook handler, FeaturePopup integration).

Purpose: Users can curate what shows in popups per layer — turn popups off for noisy layers, give them human-readable titles via `{name} — {category}` templates, and limit the property table to only the fields that matter, in user-chosen order.

Output: Migration + model + schema + service touchpoints (backend), `PopupConfig` type + `popup-template` util + `PopupConfigEditor` + `LayerEditorPanel` 4th tab + `handlePopupChange` + `FeaturePopup` title/visibleFields props + `BuilderMap` click-handler resolution (frontend), plus tests for the template util and the editor component.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260425-oxh-layer-popup-config-enable-disable-custom/260425-oxh-CONTEXT.md
@.planning/quick/260425-oxh-layer-popup-config-enable-disable-custom/260425-oxh-RESEARCH.md
@frontend/src/components/builder/LayerEditorPanel.tsx
@frontend/src/components/builder/LabelEditor.tsx
@frontend/src/components/map/FeaturePopup.tsx
@frontend/src/components/builder/BuilderMap.tsx
@frontend/src/components/builder/hooks/use-layer-map-sync.ts
@frontend/src/components/builder/hooks/use-builder-layers.ts
@backend/app/modules/catalog/maps/models.py
@backend/app/modules/catalog/maps/schemas.py
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/router.py
@backend/alembic/versions/2026_04_18_0002-add_notes_to_maps.py
@frontend/src/types/api.ts

<interfaces>
<!-- Key contracts the executor needs. Use these directly — no extra exploration required. -->

NEW TypeScript shape (frontend/src/types/api.ts, place next to LabelConfig at ~line 695):
```ts
export interface PopupConfig {
  enabled: boolean;
  expression: string | null;        // template string with {column_name} placeholders; null = no title
  visible_fields: string[] | null;  // ordered allowlist; null = show all (default); [] = show none
}
```

Add `popup_config?: PopupConfig | null` to:
- MapLayerResponse (line ~737)
- MapLayerInput (line ~838)
- SharedLayerResponse (line ~859)
- ChatMapLayer if it exists (line ~942 area — only if it already mirrors label_config)

Existing FeatureInfo (frontend/src/components/map/FeaturePopup.tsx:8-12):
```ts
export interface FeatureInfo {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo?: { name: string; type: string }[] | null;
}
```
EXTEND (do NOT add to FeaturePopupProps):
```ts
export interface FeatureInfo {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo?: { name: string; type: string }[] | null;
  title?: string | null;          // NEW — already-substituted expression output
  visibleFields?: string[] | null; // NEW — ordered allowlist; null = use columnInfo default; [] = none
}
```

Existing tab union (LayerEditorPanel.tsx:16, 28; use-builder-layers.ts:36, 177):
```ts
'style' | 'filter' | 'labels'
```
EXTEND to:
```ts
'style' | 'filter' | 'labels' | 'popup'
```
5 mechanical touchpoints — see Task 2 action.

Existing `applyLayerUpdate` signature (use-layer-map-sync.ts:33-53):
```ts
applyLayerUpdate(layerId: string, updater: LayerUpdater, applyFn?: LayerSideEffect): void
```
NEW handler `handlePopupChange` calls `applyLayerUpdate(layerId, (l) => ({ ...l, popup_config: config }))` with NO `applyFn` (popup is a React component, no MapLibre layer to add/remove — see RESEARCH §8 "Pitfalls").

Latest Alembic revision (RESEARCH §3):
- Latest revision ID: `s5t6u7v8w9x0` (2026_04_21_0001-widen_basemap_style_column.py)
- New migration: `revision = "t6u7v8w9x0y1"` (or similar — pick a fresh string), `down_revision = "s5t6u7v8w9x0"`
- Filename: `2026_04_25_0001-add_popup_config_to_map_layers.py`

JSONB column add pattern (mirrors 2026_04_18_0002-add_notes_to_maps.py):
```python
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    op.add_column(
        "map_layers",
        sa.Column("popup_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="catalog",
    )

def downgrade() -> None:
    op.drop_column("map_layers", "popup_config", schema="catalog")
```

Existing service.py touchpoints for `label_config` (3 sites; mirror exactly for `popup_config`):
- service.py:451 — `label_config=layer_data.get("label_config")` in `MapLayer(...)` constructor inside the layer-replacement loop
- service.py:625 — `label_config=layer.label_config` in the duplicate/fork loop
- service.py:874 — `"label_config": layer.label_config` in `_build_shared_layer_dict`'s return dict
PLUS router.py:101 — `label_config=layer.label_config` in `_build_layer_response` MapLayerResponse construction.

Pydantic schema additions (schemas.py):
- Line ~41-43 (MapLayerInput): add `popup_config: dict | None = Field(default=None, description="Popup configuration")`
- Line ~149 (MapLayerResponse): add `popup_config: dict | None = None`
- Line ~226 (SharedLayerResponse): add `popup_config: dict | None = None`
- Add `field_validator` on `popup_config` in MapLayerInput that enforces shape only (enabled is bool; expression is str|None; visible_fields is list[str]|None) — see Task 1 action for exact code.

Template-string parser regex (RESEARCH §1):
```ts
const PLACEHOLDER_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;
```
- Missing key at substitute time → empty string `''`
- No escape syntax — `\{` becomes literal text
- `{}` (empty) won't match — left literal
- Render via React text nodes (`<span>{title}</span>`); NEVER use `dangerouslySetInnerHTML`

Sortable picker primitive: reuse `@dnd-kit/sortable` already imported in `frontend/src/components/builder/LayerPanel.tsx:10-13` — same pattern, ~30 lines inline in PopupConfigEditor.

Click-handler short-circuit (BuilderMap.tsx:255-265):
```ts
const hits = map.queryRenderedFeatures(e.point, { layers: queryLayers });
const filteredHits = hits.filter((feature) => {
  const layerId = feature.layer.id.replace(/^layer-/, '');
  const matched = layersRef.current.find((l) => l.id === layerId);
  return matched?.popup_config?.enabled !== false; // null/undefined → show (default), only false → skip
});
if (filteredHits.length > 0) {
  const mappedFeatures = filteredHits.map((feature) => {
    const layerId = feature.layer.id.replace(/^layer-/, '');
    const matchedLayer = layersRef.current.find((l) => l.id === layerId);
    const cfg = matchedLayer?.popup_config;
    const props = (feature.properties ?? {}) as Record<string, unknown>;
    const title = cfg?.expression
      ? substitutePopupTemplate(cfg.expression, props)
      : null;
    return {
      properties: props,
      layerName: matchedLayer?.display_name || matchedLayer?.dataset_name || t('common:viewer.featureFallback'),
      columnInfo: matchedLayer?.dataset_column_info ?? null,
      title,
      visibleFields: cfg?.visible_fields ?? null,
    };
  });
  setPopupInfo({ longitude: e.lngLat.lng, latitude: e.lngLat.lat, features: mappedFeatures });
  onFeatureSelect?.(mappedFeatures[0]);
} else {
  setPopupInfo(null);
  onFeatureSelect?.(null);
}
```

i18n keys to add to `frontend/src/i18n/locales/en/builder.json` under `layerItem`:
- `popupTab`: "Popup"
- `popupTitle`: "Popup"
Plus a new `popup` namespace block for editor labels (e.g. `popup.enable`, `popup.expression`, `popup.expressionPlaceholder`, `popup.visibleFields`, `popup.unknownPlaceholders`, `popup.allFields`, `popup.noFields`).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Backend — popup_config column, schema, service plumbing, migration</name>
  <files>
    backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py,
    backend/app/modules/catalog/maps/models.py,
    backend/app/modules/catalog/maps/schemas.py,
    backend/app/modules/catalog/maps/service.py,
    backend/app/modules/catalog/maps/router.py
  </files>
  <behavior>
    - Migration upgrade adds `catalog.map_layers.popup_config` as nullable JSONB; downgrade drops it
    - `MapLayer.popup_config` is a `Mapped[dict | None]` JSONB column, default None
    - `MapLayerInput.popup_config` is `dict | None = None`; `field_validator` rejects malformed shapes (enabled not bool, expression not str|None, visible_fields not list[str]|None) but does NOT validate against column metadata (defense-in-depth shape check only — frontend is the primary UX gate per CONTEXT.md)
    - `MapLayerResponse.popup_config` and `SharedLayerResponse.popup_config` round-trip the persisted value
    - service.py and router.py copy `popup_config` in all 4 sites where `label_config` is copied (add_layer/replace loop at ~:451, fork loop at ~:625, `_build_shared_layer_dict` at ~:874, router `_build_layer_response` at ~:101)
    - PUT /maps/{id} with a layer that includes a `popup_config` body persists it; subsequent GET returns the same value
  </behavior>
  <action>
1. Create `backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py` mirroring `2026_04_18_0002-add_notes_to_maps.py`:
   - `revision = "t6u7v8w9x0y1"` (pick a fresh hex-style string in the same family)
   - `down_revision = "s5t6u7v8w9x0"` (current head per RESEARCH §3)
   - `from sqlalchemy.dialects import postgresql`
   - `upgrade()`: `op.add_column("map_layers", sa.Column("popup_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema="catalog")`
   - `downgrade()`: `op.drop_column("map_layers", "popup_config", schema="catalog")`
   - Module docstring: "Add popup_config column to map_layers."

2. `backend/app/modules/catalog/maps/models.py:112` — add immediately after the `label_config` line:
   ```python
   popup_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
   ```

3. `backend/app/modules/catalog/maps/schemas.py`:
   - At the top, ensure `from typing import Any` is imported if not already.
   - Inside `MapLayerInput` (after the `label_config` Field at ~:41-43), add:
     ```python
     popup_config: dict | None = Field(
         default=None, description="Popup configuration: {enabled, expression, visible_fields}"
     )
     ```
   - Add a `field_validator` immediately after the field declaration block of `MapLayerInput`:
     ```python
     @field_validator("popup_config")
     @classmethod
     def _validate_popup_config_shape(cls, v: dict | None) -> dict | None:
         if v is None:
             return None
         if not isinstance(v, dict):
             raise ValueError("popup_config must be an object or null")
         enabled = v.get("enabled")
         if not isinstance(enabled, bool):
             raise ValueError("popup_config.enabled must be a boolean")
         expr = v.get("expression", None)
         if expr is not None and not isinstance(expr, str):
             raise ValueError("popup_config.expression must be a string or null")
         vf = v.get("visible_fields", None)
         if vf is not None:
             if not isinstance(vf, list) or not all(isinstance(x, str) for x in vf):
                 raise ValueError("popup_config.visible_fields must be a list of strings or null")
         allowed = {"enabled", "expression", "visible_fields"}
         extras = set(v.keys()) - allowed
         if extras:
             raise ValueError(f"popup_config has unexpected keys: {sorted(extras)}")
         return v
     ```
   - Inside `MapLayerResponse` (after `label_config: dict | None = None` at ~:149), add:
     ```python
     popup_config: dict | None = None
     ```
   - Inside `SharedLayerResponse` (after `label_config: dict | None = None` at ~:226), add:
     ```python
     popup_config: dict | None = None
     ```

4. `backend/app/modules/catalog/maps/service.py` — add `popup_config` to all 3 `label_config` sites:
   - Line ~:451 inside `MapLayer(...)` constructor in the layer-replace path: add `popup_config=layer_data.get("popup_config"),` directly after the `label_config=` line.
   - Line ~:625 inside the fork/duplicate `MapLayer(...)` constructor: add `popup_config=layer.popup_config,` after `label_config=layer.label_config,`.
   - Line ~:874 inside `_build_shared_layer_dict`'s return dict: add `"popup_config": layer.popup_config,` after `"label_config": layer.label_config,`.

5. `backend/app/modules/catalog/maps/router.py:101` (inside `_build_layer_response`) — after `label_config=layer.label_config,` add:
   ```python
   popup_config=layer.popup_config,
   ```

6. Run the migration locally to verify it applies cleanly: `docker compose exec api alembic upgrade head` (or whatever the project uses — check the existing pattern; if it's `alembic upgrade head` from inside the backend container, follow that). Then `alembic downgrade -1` to confirm `downgrade()` works, then `alembic upgrade head` again.

7. Run backend tests targeting maps: `docker compose exec api pytest backend/app/modules/catalog/maps/ -x` (or local equivalent — match existing project test invocation). Existing tests must pass — no regressions to `label_config` plumbing.
  </action>
  <verify>
    <automated>cd backend && python -c "from app.modules.catalog.maps.models import MapLayer; assert hasattr(MapLayer, 'popup_config'), 'MapLayer.popup_config missing'; print('OK')" && python -c "from app.modules.catalog.maps.schemas import MapLayerInput, MapLayerResponse, SharedLayerResponse; m=MapLayerInput(dataset_id='00000000-0000-0000-0000-000000000000', popup_config={'enabled': True, 'expression': '{x}', 'visible_fields': ['x']}); assert m.popup_config['enabled'] is True; assert 'popup_config' in MapLayerResponse.model_fields; assert 'popup_config' in SharedLayerResponse.model_fields; print('OK')" && grep -c '^[^#]*popup_config' backend/app/modules/catalog/maps/service.py | (read n; [ "$n" -ge 3 ] || (echo "Expected >=3 popup_config refs in service.py, got $n"; exit 1)) && grep -q 'popup_config=layer.popup_config' backend/app/modules/catalog/maps/router.py && grep -q 'popup_config' backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py</automated>
  </verify>
  <done>
    Migration file exists with correct down_revision; `MapLayer.popup_config` is a JSONB nullable column; `MapLayerInput`/`MapLayerResponse`/`SharedLayerResponse` all expose `popup_config`; field_validator rejects bad shapes; service.py persists/copies/serializes `popup_config` in all 3 sites; router.py includes it in `_build_layer_response`; alembic upgrade + downgrade + upgrade run without error; existing maps tests pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Frontend — types, popup-template util, PopupConfigEditor, LayerEditorPanel 4th tab, handlePopupChange</name>
  <files>
    frontend/src/types/api.ts,
    frontend/src/lib/popup-template.ts,
    frontend/src/lib/__tests__/popup-template.test.ts,
    frontend/src/components/builder/PopupConfigEditor.tsx,
    frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx,
    frontend/src/components/builder/LayerEditorPanel.tsx,
    frontend/src/components/builder/hooks/use-layer-map-sync.ts,
    frontend/src/components/builder/hooks/use-builder-layers.ts,
    frontend/src/i18n/locales/en/builder.json
  </files>
  <behavior>
    - `extractPlaceholders('{a}, {b} text')` → `['a', 'b']`; `extractPlaceholders('plain text')` → `[]`; `extractPlaceholders('{}{x}{1bad}')` → `['x']`
    - `validatePlaceholders(['a','b'], ['a','b','c'])` → `{ ok: true, unknown: [] }`; `validatePlaceholders(['a','x'], ['a','b','c'])` → `{ ok: false, unknown: ['x'] }`
    - `substitutePopupTemplate('{name} — {missing}', { name: 'Foo' })` → `'Foo — '` (missing → empty string)
    - `substitutePopupTemplate('{count}', { count: 42 })` → `'42'` (string-coerced)
    - PopupConfigEditor toggle off → calls `onPopupChange({ enabled: false, expression: null, visible_fields: null })` (or null — pick one shape and stay consistent; we use `{ enabled: false, ... }` so the explicit "off" intent persists)
    - PopupConfigEditor toggle on with no prior config → defaults to `{ enabled: true, expression: '', visible_fields: null }` (expression empty, all fields visible)
    - Typing `{unknownColumn}` shows red border + "Unknown placeholder: unknownColumn" helper text within ~250ms
    - Sortable picker: drag-reorder updates `visible_fields` order; checkbox toggle adds/removes from the array; "show all" toggle sets `visible_fields: null`; "show none" leaves an empty array
    - LayerEditorPanel renders the new "Popup" tab when a vector layer is expanded; clicking it invokes `handlers.onTabChange(layer.id, 'popup')`
    - `handlePopupChange` updates `localLayers[id].popup_config` via `applyLayerUpdate` with NO map side-effect (the `applyFn` is omitted)
  </behavior>
  <action>
1. **`frontend/src/types/api.ts`** — at line ~695 (right after `LabelConfig`), add:
   ```ts
   // Popups
   export interface PopupConfig {
     enabled: boolean;
     expression: string | null;
     visible_fields: string[] | null;
   }
   ```
   Then add `popup_config?: PopupConfig | null;` to:
   - `MapLayerResponse` (after the `label_config?: LabelConfig | null;` line at ~754)
   - `MapLayerInput` (after `label_config?: LabelConfig | null;` at ~847)
   - `SharedLayerResponse` (after `label_config?: LabelConfig | null;` at ~872)
   - `ChatMapLayer` if it exists and already mirrors `label_config` — search by `grep -n "label_config" frontend/src/types/api.ts`. If it's there, mirror the field in the same position.

2. **`frontend/src/lib/popup-template.ts`** (NEW) — implement three small functions, no dependencies:
   ```ts
   const PLACEHOLDER_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

   export function extractPlaceholders(template: string): string[] {
     if (!template) return [];
     const out: string[] = [];
     for (const m of template.matchAll(PLACEHOLDER_RE)) {
       const key = m[1];
       if (!out.includes(key)) out.push(key);
     }
     return out;
   }

   export function validatePlaceholders(
     placeholders: string[],
     knownColumns: string[],
   ): { ok: boolean; unknown: string[] } {
     const known = new Set(knownColumns);
     const unknown = placeholders.filter((k) => !known.has(k));
     return { ok: unknown.length === 0, unknown };
   }

   export function substitutePopupTemplate(
     template: string,
     properties: Record<string, unknown>,
   ): string {
     return template.replace(PLACEHOLDER_RE, (_match, key: string) => {
       const v = properties[key];
       if (v === null || v === undefined) return '';
       return String(v);
     });
   }
   ```

3. **`frontend/src/lib/__tests__/popup-template.test.ts`** (NEW) — Vitest unit tests covering:
   - `extractPlaceholders`: empty string, no placeholders, single, multiple, duplicates de-duped, invalid `{1bad}` and `{}` ignored, mixed valid/invalid
   - `validatePlaceholders`: all known, none unknown, some unknown, empty placeholders list
   - `substitutePopupTemplate`: simple substitution, missing key → empty string, number coercion, null → empty, multiple placeholders in one string, no-placeholder template returns unchanged, `{}` and `{1bad}` left literal
   Use the same Vitest pattern visible in existing files like `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts`.

4. **`frontend/src/components/builder/PopupConfigEditor.tsx`** (NEW) — mirror `LabelEditor.tsx` structure:
   - Props: `{ columns: { name: string; type: string }[]; popupConfig: PopupConfig | null; onPopupChange: (config: PopupConfig | null) => void; }`
   - Use the same i18n hook: `const { t } = useTranslation('builder');`
   - Lay out:
     - Top row: `<Switch>` for enable/disable (use `@/components/ui/switch` like LabelEditor:60-75 pattern). Toggling on with no prior config sets `{ enabled: true, expression: '', visible_fields: null }`. Toggling off sets `{ enabled: false, expression: popupConfig?.expression ?? null, visible_fields: popupConfig?.visible_fields ?? null }` (preserve user's prior values so re-enabling restores them).
     - Expression field: `<textarea>` (or `<Input>` — pick the existing UI primitive most similar to label text input). Show `placeholder="{city}, {state}"`. Compute `placeholders = useMemo(() => extractPlaceholders(expr), [expr])` and `validation = useMemo(() => validatePlaceholders(placeholders, columns.map(c => c.name)), [placeholders, columns])`. On change, debounce with `setTimeout`/`clearTimeout` for 250ms before re-running validation against the latest value (use a `useRef<number | null>` or the existing debounce idiom in the codebase if there is one — search by `grep -rn "setTimeout" frontend/src/components/builder/`). Apply red border + helper text "Unknown placeholders: {list.join(', ')}" when `!validation.ok`.
     - Visible fields picker:
       - Mode toggle: "Show all (default)" sets `visible_fields: null`; "Custom selection" sets it to `[]` (empty allowlist) initially.
       - When custom: render a sortable list using `@dnd-kit/core` + `@dnd-kit/sortable` (same imports/strategy as `frontend/src/components/builder/LayerPanel.tsx:10-13`). Each item is a checkbox-labeled column name. Checking a column appends it to the list; unchecking removes it. Drag handle on each row reorders. The unchecked columns appear below as a "Add fields" panel of unchecked options the user can click to add. Keep it inline (~30-50 lines is fine — RESEARCH §7 confirms no shared primitive exists).
   - Disable Save side: this component does not own save — it just calls `onPopupChange`. The parent `useBuilderLayers` flow already debounces saves via `hasUnsavedChanges`. The locked-spec "block save if invalid" requirement is enforced at the `<MapBuilderToolbar>` (or wherever the save button lives) by checking layer popup configs. Implement this gate by exporting a helper from `popup-template.ts`:
     ```ts
     export function isPopupConfigValid(cfg: PopupConfig | null, columns: string[]): boolean {
       if (!cfg || !cfg.enabled) return true;
       if (cfg.expression == null || cfg.expression === '') return true;
       const phs = extractPlaceholders(cfg.expression);
       return validatePlaceholders(phs, columns).ok;
     }
     ```
     and consume it in `use-builder-layers.ts` `handleSave` (find via `grep -n "handleSave\|hasUnsavedChanges" frontend/src/components/builder/hooks/use-builder-layers.ts`). If any layer's popup_config is invalid, call `toast.error(t('toasts.popupConfigInvalid'))` and `return` early. Add the i18n key to the `toasts` namespace.
   - Important: render the substituted preview text using a plain `<span>{previewTitle}</span>` JSX expression — NEVER `dangerouslySetInnerHTML` (RESEARCH §1 XSS note).

5. **`frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx`** (NEW) — RTL/Vitest tests covering:
   - Renders disabled state when `popupConfig === null` and toggling on emits `{ enabled: true, expression: '', visible_fields: null }`
   - Toggling off from enabled emits `{ enabled: false, ... }` and preserves expression/visible_fields
   - Typing an unknown placeholder shows the validation error after 250ms (use `vi.useFakeTimers()` + `vi.advanceTimersByTime(300)`)
   - Switching to "Custom selection" mode emits `visible_fields: []`
   - Toggling a column checkbox appends it to `visible_fields` in clicked order
   - (Drag reorder may be hard to test deterministically with @dnd-kit — skip if it requires excessive setup; covered by manual UAT in must_haves.)
   Use existing test infra: same imports as `LayerStyleEditor.test.tsx`.

6. **`frontend/src/components/builder/LayerEditorPanel.tsx`** — extend the tab union and add the popup tab/panel:
   - Line 16 (`LayerEditorHandlers.onTabChange`): change `'style' | 'filter' | 'labels'` to `'style' | 'filter' | 'labels' | 'popup'`. Add a new handler property: `onPopupChange: (layerId: string, config: PopupConfig | null) => void;`.
   - Line 28 (`activeTab` prop): change union to `'style' | 'filter' | 'labels' | 'popup' | null`.
   - Line 96 (tab array): change to `(['style', 'filter', 'labels', 'popup'] as const)`.
   - Lines 97-101 (filter logic): add a clause `if (tab === 'popup') return caps.supportsFilterEditor || caps.supportsLabelEditor;` — popup is available wherever vector tabs are; if a clearer capability flag exists in `getLayerCapabilities`, use it. Worst-case acceptable: gate on `!isRaster` only (which is already implicit because the tab block is wrapped in `{!isRaster && ...}`).
   - After the existing `{activeTab === 'labels' && ...}` block (~:147-156), add:
     ```tsx
     {activeTab === 'popup' && (
       <div role="tabpanel" id={`tabpanel-${layer.id}-popup`} aria-labelledby={`tab-${layer.id}-popup`}>
         <PopupConfigEditor
           columns={columns}
           popupConfig={layer.popup_config ?? null}
           onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
         />
       </div>
     )}
     ```
   - Add `import { PopupConfigEditor } from './PopupConfigEditor';` at the top with the other component imports.
   - Add `import type { PopupConfig } from '@/types/api';` (or extend the existing `import type { ... } from '@/types/api'` line).

7. **`frontend/src/components/builder/hooks/use-layer-map-sync.ts`**:
   - Add `import type { PopupConfig } from '@/types/api';` (extend existing import).
   - After `handleLabelChange` (~:273-300 block), add:
     ```ts
     const handlePopupChange = useCallback(
       (layerId: string, config: PopupConfig | null) => {
         applyLayerUpdate(layerId, (l) => ({ ...l, popup_config: config }));
         // No map side-effect: popup is a React component, not a MapLibre layer.
       },
       [applyLayerUpdate],
     );
     ```
   - Add `handlePopupChange` to the hook's return object (find the return statement at the bottom of the function).

8. **`frontend/src/components/builder/hooks/use-builder-layers.ts`**:
   - Line 36 (state): change `useState<'style' | 'filter' | 'labels' | null>(null)` to `useState<'style' | 'filter' | 'labels' | 'popup' | null>(null)`.
   - Line 64-65 destructure: add `handlePopupChange,` to the list pulled from `useLayerMapSync(...)`.
   - Line 177 (`handleTabChange`): change parameter type to `'style' | 'filter' | 'labels' | 'popup'`.
   - Find where the hook returns its handlers (likely near the bottom). Add `handlePopupChange` to the returned bag so it can be wired up by the consumer (likely `MapBuilder.tsx` or wherever `handlers={...}` is built for `LayerEditorPanel`).
   - Find the consumer that builds `handlers: LayerEditorHandlers` and pass `onPopupChange: handlePopupChange`. Search: `grep -rn "onLabelChange:\s*handle" frontend/src/components/builder/` to find the wire-up site, and add `onPopupChange: handlePopupChange,` directly after.

9. **`frontend/src/i18n/locales/en/builder.json`** — add inside the `layerItem` block (alongside `labelsTab`/`styleTab`):
   ```json
   "popupTab": "Popup",
   "popupTitle": "Popup"
   ```
   And add a new top-level `popup` namespace block (mirroring `labels` if it exists):
   ```json
   "popup": {
     "enable": "Enable popup for this layer",
     "expression": "Title template",
     "expressionHelp": "Use {column_name} placeholders. Example: {city}, {state}",
     "expressionPlaceholder": "{city}, {state}",
     "unknownPlaceholders": "Unknown placeholders: {{list}}",
     "visibleFields": "Visible fields",
     "visibleFieldsAll": "Show all fields (default)",
     "visibleFieldsCustom": "Custom selection",
     "addField": "Add field",
     "noFieldsSelected": "No fields selected (only the title will show)"
   }
   ```
   And add to `toasts`:
   ```json
   "popupConfigInvalid": "Cannot save: one or more layers have invalid popup expressions"
   ```

10. Run frontend tests + typecheck + lint:
    - `cd frontend && npm run typecheck`
    - `cd frontend && npm test -- --run popup-template`
    - `cd frontend && npm test -- --run PopupConfigEditor`
    - `cd frontend && npm run lint`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run typecheck && npm test -- --run popup-template PopupConfigEditor && npm run lint && grep -q "PopupConfig" src/types/api.ts && grep -q "popup_config" src/types/api.ts && grep -q "extractPlaceholders\|substitutePopupTemplate" src/lib/popup-template.ts && grep -q "PopupConfigEditor" src/components/builder/LayerEditorPanel.tsx && grep -q "handlePopupChange" src/components/builder/hooks/use-layer-map-sync.ts && grep -q "'popup'" src/components/builder/LayerEditorPanel.tsx && grep -q "popupTab" src/i18n/locales/en/builder.json</automated>
  </verify>
  <done>
    `PopupConfig` type exported and added to MapLayerResponse/Input/SharedLayerResponse; `popup-template.ts` exports `extractPlaceholders`, `validatePlaceholders`, `substitutePopupTemplate`, `isPopupConfigValid` and has passing unit tests; `PopupConfigEditor.tsx` exists with passing component tests; `LayerEditorPanel.tsx` shows the 4th "Popup" tab with type-safe union; `use-layer-map-sync.ts` exports `handlePopupChange`; `use-builder-layers.ts` widens the tab union and wires `onPopupChange`; i18n keys added; `npm run typecheck`, `npm run lint`, and the targeted Vitest runs all pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Frontend — wire FeaturePopup title/visibleFields + BuilderMap click-handler resolution</name>
  <files>
    frontend/src/components/map/FeaturePopup.tsx,
    frontend/src/components/builder/BuilderMap.tsx
  </files>
  <behavior>
    - Clicking a feature on a layer with `popup_config.enabled === false` does NOT open a popup for that feature (other layers' features at the same point still show)
    - Clicking a feature on a layer with `popup_config.expression = '{name}'` shows the substituted title (e.g. `"Acme Corp"`) as a heading inside the popup, above the existing property table
    - Clicking a feature on a layer with `popup_config.visible_fields = ['name', 'city']` shows ONLY those two rows in the property table, in that order — even if the underlying feature has more properties
    - `popup_config.visible_fields = []` shows zero rows (empty state) but keeps the title visible
    - `popup_config = null` or `popup_config.enabled !== false` with no expression preserves existing default behavior — no regression
    - No `dangerouslySetInnerHTML` introduced anywhere; title rendered via JSX text node only
  </behavior>
  <action>
1. **`frontend/src/components/map/FeaturePopup.tsx`**:
   - Extend `FeatureInfo` (lines 8-12) to:
     ```ts
     export interface FeatureInfo {
       properties: Record<string, unknown>;
       layerName: string;
       columnInfo?: { name: string; type: string }[] | null;
       title?: string | null;
       visibleFields?: string[] | null;
     }
     ```
   - Inside the component body, after destructuring `feature` (~line 51), pull out `title` and `visibleFields`:
     ```ts
     const { properties, layerName, columnInfo, title, visibleFields } = feature;
     ```
   - Replace the `visibleEntries` computation (lines 64-78) with allowlist-aware logic:
     ```ts
     // 1) Drop internal + geometry keys (current behavior)
     const baseEntries = Object.entries(properties).filter(([key]) => {
       if (key.startsWith('_')) return false;
       if (EXCLUDED_KEYS.has(key)) return false;
       return true;
     });

     // 2) If visibleFields is provided, use it as an ordered allowlist.
     //    null/undefined → fall back to columnInfo allowlist (legacy default).
     //    [] → return zero entries (intentional "title only" mode).
     let visibleEntries: [string, unknown][];
     if (visibleFields !== undefined && visibleFields !== null) {
       const propMap = new Map(baseEntries);
       visibleEntries = visibleFields
         .filter((k) => propMap.has(k))
         .map((k) => [k, propMap.get(k)] as [string, unknown]);
     } else if (columnInfo) {
       const columnNames = new Set(columnInfo.map((c) => c.name));
       visibleEntries = baseEntries.filter(([key]) => columnNames.has(key));
     } else {
       visibleEntries = baseEntries;
     }
     ```
   - Render the title above the existing header. Find the JSX block that starts at line 95 (`<Popup ...>`). Inside the `<div className="text-xs">` (line 103), insert immediately AFTER the opening `<div>` and BEFORE the existing header row:
     ```tsx
     {title && (
       <div className="font-semibold text-sm mb-1 break-words" style={{ whiteSpace: 'pre-wrap' }}>
         {title}
       </div>
     )}
     ```
     (Use `whiteSpace: pre-wrap` per RESEARCH §1 — preserves any newlines the user typed without `<br/>` injection.)
   - The existing "no attributes" empty state (lines 136-138) already handles the `visibleEntries.length === 0` case correctly when `visible_fields = []` and we still want title-only — verify it does not also hide the title (it does not; the empty state is inside the table, not above it).

2. **`frontend/src/components/builder/BuilderMap.tsx`** (lines 245-276) — replace the click handler body to filter hits and substitute titles:
   - Add the import at the top with the other imports: `import { substitutePopupTemplate } from '@/lib/popup-template';`
   - Replace the contents of `handleClick` (245-276) with:
     ```ts
     const handleClick = (e: MapMouseEvent) => {
       if (!map.isStyleLoaded()) return;
       if (measureActiveRef.current) return;
       const queryLayers = queryLayerIdsRef.current;

       if (queryLayers.length === 0) {
         setPopupInfo(null);
         return;
       }

       const hits = map.queryRenderedFeatures(e.point, { layers: queryLayers });

       // Filter out features whose source layer has popups disabled
       const filteredHits = hits.filter((feature) => {
         const layerId = feature.layer.id.replace(/^layer-/, '');
         const matched = layersRef.current.find((l) => l.id === layerId);
         // null/undefined popup_config → enabled by default; only explicit false suppresses
         return matched?.popup_config?.enabled !== false;
       });

       if (filteredHits.length > 0) {
         const mappedFeatures = filteredHits.map((feature) => {
           const layerId = feature.layer.id.replace(/^layer-/, '');
           const matchedLayer = layersRef.current.find((l) => l.id === layerId);
           const cfg = matchedLayer?.popup_config;
           const props = (feature.properties ?? {}) as Record<string, unknown>;
           const title = cfg?.expression
             ? substitutePopupTemplate(cfg.expression, props)
             : null;
           return {
             properties: props,
             layerName: matchedLayer?.display_name || matchedLayer?.dataset_name || t('common:viewer.featureFallback'),
             columnInfo: matchedLayer?.dataset_column_info ?? null,
             title,
             visibleFields: cfg?.visible_fields ?? null,
           };
         });
         setPopupInfo({
           longitude: e.lngLat.lng,
           latitude: e.lngLat.lat,
           features: mappedFeatures,
         });
         onFeatureSelect?.(mappedFeatures[0]);
       } else {
         setPopupInfo(null);
         onFeatureSelect?.(null);
       }
     };
     ```
   - Verify there is no other location where `popupInfo.features` is built (search `grep -n "FeatureInfo\|setPopupInfo" frontend/src/components/builder/BuilderMap.tsx`). If a second site exists, mirror the same fields.

3. Run typecheck + smoke test: build + start dev server (or run existing BuilderMap unit tests).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run typecheck && npm test -- --run BuilderMap FeaturePopup 2>&1 | tail -20 && grep -q "title?:\s*string" src/components/map/FeaturePopup.tsx && grep -q "visibleFields?" src/components/map/FeaturePopup.tsx && grep -q "substitutePopupTemplate" src/components/builder/BuilderMap.tsx && grep -c "popup_config" src/components/builder/BuilderMap.tsx | (read n; [ "$n" -ge 2 ] || (echo "Expected >=2 popup_config refs in BuilderMap.tsx, got $n"; exit 1)) && ! grep -q "dangerouslySetInnerHTML" src/components/map/FeaturePopup.tsx</automated>
  </verify>
  <done>
    `FeatureInfo` extended with optional `title` and `visibleFields`; title renders as a `<div>` above the existing header using `white-space: pre-wrap`; `visibleEntries` honors ordered allowlist (`null` → existing columnInfo behavior, `[]` → zero rows, `['a','b']` → those two in that order); `BuilderMap.handleClick` filters hits by `popup_config?.enabled !== false`, substitutes the expression into `title`, and passes `visible_fields` per feature; no `dangerouslySetInnerHTML`; typecheck and tests pass; manual smoke (one layer with popups disabled does NOT open popups but other layers do; title + custom-fields combination renders correctly) covered by must_haves truths.
  </done>
</task>

</tasks>

<verification>
- Backend migration: `alembic upgrade head` runs cleanly; `\d catalog.map_layers` shows `popup_config jsonb`
- Backend round-trip: PUT a map layer with `popup_config: {enabled: true, expression: "{x}", visible_fields: ["x"]}`; GET the same map; the value survives unchanged
- Backend reject: PUT with `popup_config: {enabled: "yes"}` → 422 with mention of "enabled must be a boolean"
- Backend fork: duplicate a map whose layer has popup_config; the new map's layer has the same popup_config
- Frontend unit tests: `popup-template.test.ts` and `PopupConfigEditor.test.tsx` pass
- Frontend typecheck: `npm run typecheck` passes (no `any`, no missing fields)
- Frontend lint: `npm run lint` passes
- UI: open Map Builder, expand a vector layer, click "Popup" tab — editor renders; toggle on; type `{name}` (assuming `name` is a column) — no error; type `{nonexistent}` — red border + error message after ~250ms; save attempt while invalid → toast error and save blocked
- UI: clicking a feature on a layer with `enabled: false` shows no popup for that feature; clicking a feature on a layer with `expression: "{name}"` shows the substituted title above the existing property table; clicking a feature with `visible_fields: ["name", "city"]` shows only those two rows in that order
- Other layers unaffected: with two layers stacked at the same click point, disabling popups on layer A still opens the popup for layer B's feature
- No XSS regression: `grep -r "dangerouslySetInnerHTML" frontend/src` returns zero matches
</verification>

<success_criteria>
- [ ] Migration `2026_04_25_0001-add_popup_config_to_map_layers.py` exists, applies, and reverses cleanly
- [ ] `MapLayer.popup_config` JSONB column exists
- [ ] `MapLayerInput`, `MapLayerResponse`, `SharedLayerResponse` all expose `popup_config` and `popup_config` round-trips through PUT → GET
- [ ] `PopupConfig` TypeScript interface defined and used on `MapLayerResponse`/`MapLayerInput`/`SharedLayerResponse`
- [ ] `frontend/src/lib/popup-template.ts` exports `extractPlaceholders`, `validatePlaceholders`, `substitutePopupTemplate`, `isPopupConfigValid` with unit tests passing
- [ ] `PopupConfigEditor.tsx` provides toggle + expression field with live (debounced ~250ms) validation + sortable visible-fields picker, with component tests passing
- [ ] `LayerEditorPanel` shows a 4th "Popup" tab for vector layers; tab union `'style' | 'filter' | 'labels' | 'popup'` propagated through 5 sites (per RESEARCH §8)
- [ ] `handlePopupChange` exists in `use-layer-map-sync.ts` and is wired through `use-builder-layers.ts` to `LayerEditorPanel`
- [ ] `FeaturePopup` renders `title` above the existing header and respects `visibleFields` as an ordered allowlist (null = legacy default; [] = zero rows; ordered list = those keys in order)
- [ ] `BuilderMap` click handler filters hits by `popup_config?.enabled !== false` and substitutes the expression into `title` for each surviving feature
- [ ] Save is blocked with a toast when any layer's popup expression has unknown placeholders
- [ ] No `dangerouslySetInnerHTML` introduced anywhere
- [ ] `npm run typecheck`, `npm run lint`, targeted Vitest runs, and existing backend maps tests all pass
</success_criteria>

<output>
After completion, create `.planning/quick/260425-oxh-layer-popup-config-enable-disable-custom/260425-oxh-SUMMARY.md` documenting what was implemented (artifacts, decisions, any deviations from plan), per the standard SUMMARY template.
</output>
