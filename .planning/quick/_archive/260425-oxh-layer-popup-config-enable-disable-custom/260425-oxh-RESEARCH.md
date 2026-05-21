---
quick_id: 260425-oxh
description: "layer popup config: enable/disable + custom expression with validation"
status: research_complete
---

# Quick Task 260425-oxh — Research

**Researched:** 2026-04-25
**Domain:** GeoLens map builder — popup config (mirror of `label_config`)
**Confidence:** HIGH (everything verified in-tree; no external libraries needed)

## Summary

Every required pattern already exists in the codebase. The popup config feature is a clean diagonal copy of `label_config`: same JSONB column shape, same Pydantic `dict | None` schema, same hook plumbing (`useLayerMapSync.handleLabelChange`), same column source (`layer.dataset_column_info`). React's default JSX escaping handles XSS for the title rendering; no `dangerouslySetInnerHTML` exists anywhere in the codebase, and we shouldn't introduce one. `@dnd-kit/sortable` is already installed and in use by `LayerPanel.tsx` — the visible-fields sortable picker should reuse the same primitive.

**Primary recommendation:** Mirror `label_config` end-to-end. Build a `parsePopupTemplate()` util in `frontend/src/lib/` (single regex, ~15 lines). Render the title as a plain `<span>{substituted}</span>` — React escapes by default. Add a new `popup_config: dict | None` column with the next migration revision (down_revision = `s5t6u7v8w9x0`).

## Key Findings

### 1. Template string parser — build it new, ~15 lines

No existing template util in `frontend/src/lib/` or `frontend/src/utils/` (Glob: zero matches for `template*.ts`).

**Recommended regex:** `/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g` — matches `{column_name}` for valid SQL-ish identifiers. Extraction:

```ts
function extractKeys(tpl: string): string[] {
  return [...tpl.matchAll(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g)].map(m => m[1]);
}
```

**Edge cases — keep them simple per CONTEXT.md decisions:**
- **Escaping `\{`** — NOT in the locked spec; don't implement. If user types `\{`, the `\` becomes literal text and `{x}` still substitutes. Document as "no escape syntax."
- **Empty `{}`** — regex requires `[a-zA-Z_]` start, so `{}` won't match — left as literal. Good.
- **Nested braces `{{x}}`** — regex matches the inner `{x}`; outer `{...}` left as literal. Acceptable.
- **Missing key at render time** — substitute with `''` per CONTEXT.md ("string-coerced, missing → empty string").

**XSS safety — confirmed via Grep `dangerouslySetInnerHTML` across `frontend/src`: zero matches.** Rendering substituted output via JSX text nodes (e.g. `<span>{title}</span>`) is automatically escaped by React 19. **Do not introduce `dangerouslySetInnerHTML`** — line breaks, if needed, can be done with `white-space: pre-wrap` CSS on the title element instead of `<br/>` injection.

### 2. Column source — `layer.dataset_column_info`

Single source for both validator and visible-fields picker. `LabelEditor` receives it from `LayerEditorPanel.tsx:40` (`const columns = layer.dataset_column_info ?? []`) which is wired from the API field `MapLayerResponse.dataset_column_info` (`frontend/src/types/api.ts:744`). Backend hydrates it in `backend/app/modules/catalog/maps/service.py` (referenced at `:872` block). Shape: `{ name: string; type: string }[]`. **Use the exact same prop pipeline** (`columns={layer.dataset_column_info ?? []}`) for `PopupConfigEditor`. No new API call needed.

### 3. JSONB column + Alembic migration — mirror `2026_04_18_0002`

Latest single-column-add migration: `backend/alembic/versions/2026_04_18_0002-add_notes_to_maps.py` (lines 19-28). Pattern:

```python
def upgrade() -> None:
    op.add_column(
        "map_layers",
        sa.Column("popup_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="catalog",
    )

def downgrade() -> None:
    op.drop_column("map_layers", "popup_config", schema="catalog")
```

Original `label_config` JSONB column was created in `backend/alembic/versions/0002_initial_tables.py:977` via `postgresql.JSONB(astext_type=sa.Text()), nullable=True` — same shape we need.

**Latest revision ID is `s5t6u7v8w9x0`** (`backend/alembic/versions/2026_04_21_0001-widen_basemap_style_column.py:15`). New migration: `down_revision = "s5t6u7v8w9x0"`. Filename convention: `2026_04_25_0001-add_popup_config_to_map_layers.py`. Need `from sqlalchemy.dialects import postgresql` for `JSONB`.

### 4. Pydantic schema — loose `dict | None`, no `extra="forbid"`

`label_config` is declared as **untyped `dict | None`** at `backend/app/modules/catalog/maps/schemas.py:41-43` (input) and `:149` (response). No nested Pydantic model; no `extra="forbid"`. Only the three response models use `model_config = ConfigDict(from_attributes=True)` (`schemas.py:154, 183, 203`) — not strict mode. Server-side validation lives in router/service code, not the schema.

**Decision:** Mirror exactly — add `popup_config: dict | None = Field(default=None, description="Popup configuration")` to `MapLayerInput` (`:19-54`) and `popup_config: dict | None = None` to `MapLayerResponse` (`:130-154`) and `SharedLayerResponse` (`:211-232`). For defense-in-depth validation per CONTEXT.md, add a `field_validator` on `popup_config` in `MapLayerInput` that parses `expression`'s `{...}` keys but does NOT enforce them against the column list (the backend doesn't have column metadata at that point — only ID — and adding a DB lookup in validation is over-engineering for the locked spec). Keep schema-level validation to: shape check (enabled is bool, expression is str|null, visible_fields is list[str]|null) + reject unknown extra keys via a simple TypedDict-style check.

### 5. FeaturePopup integration — additive props

Current props (`frontend/src/components/map/FeaturePopup.tsx:14-19`):
```ts
interface FeaturePopupProps {
  longitude: number;
  latitude: number;
  features: FeatureInfo[];
  onClose: () => void;
}
```
And `FeatureInfo` (`:8-12`): `properties`, `layerName`, `columnInfo`.

Existing visible-field filter is already at `:65-78` — entries are filtered (1) by `_`-prefix exclusion, (2) by `EXCLUDED_KEYS = {'geom','geometry'}` (`:21`), and (3) by `columnInfo` allowlist if present. **The `visible_fields` allowlist is essentially a per-feature override of step 3 with explicit ordering.**

**Smallest additive prop change** — extend `FeatureInfo`, NOT `FeaturePopupProps`:
```ts
interface FeatureInfo {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo?: { name: string; type: string }[] | null;
  // NEW
  title?: string | null;          // already-substituted expression output
  visibleFields?: string[] | null; // ordered allowlist; null = use columnInfo default
}
```
Render title as a `<div>` above the existing header at `:104-132`. For `visibleFields`, replace lines 76-78 with: if `visibleFields !== undefined && visibleFields !== null`, build entries by mapping over `visibleFields` (preserves order); else fall back to current logic. Empty `[]` → no rows (current "no attributes" empty state at `:136-138` already handles this).

**Substitution happens upstream** — `BuilderMap`'s click handler does the parse+substitute, never the popup. Keeps `FeaturePopup` agnostic.

### 6. Click-handler short-circuit — synchronous lookup via `layersRef.current`

`BuilderMap.tsx:245-276` already maps clicked features back to layers using `layersRef.current.find((l) => l.id === layerId)` (`:259`) — synchronous, in-memory. `layersRef` is updated on every render at `:131-132`. The popup config lookup is trivial:

```ts
const matchedLayer = layersRef.current.find((l) => l.id === layerId);
const popupCfg = matchedLayer?.popup_config;
if (popupCfg && popupCfg.enabled === false) return; // skip this feature entirely
```

**Subtlety — multi-hit case (`:255` `queryRenderedFeatures`):** when click hits multiple stacked features from different layers, current code adds ALL hits to the popup carousel. Per CONTEXT.md ("Other layers on the map remain unaffected"), filter the `hits` array by `popup_config?.enabled !== false` BEFORE building `mappedFeatures` (`:257-265`). If filtered list is empty, `setPopupInfo(null)` like the "no hits" branch (`:272-274`).

### 7. Sortable multi-select — already installed, use `@dnd-kit/sortable`

`frontend/package.json:19-21` shows `@dnd-kit/core ^6.3.1`, `@dnd-kit/sortable ^10.0.0`, `@dnd-kit/utilities ^3.2.2` already installed. **In active use:** `frontend/src/components/builder/LayerPanel.tsx:10-13` uses `SortableContext`, `verticalListSortingStrategy`, `sortableKeyboardCoordinates`, `useSortable`. Rip the same pattern.

**No existing sortable multi-select component exists** in `frontend/src/components/ui/` (Glob confirmed). Build one inline in `PopupConfigEditor.tsx` — for the locked scope (one-off picker, ordered string list of column names), it's ~30 lines. No new dependency.

### 8. Pitfalls / Gotchas

- **Popup re-render perf:** `FeaturePopup` is mounted inside `MapGL` children at `BuilderMap.tsx:459-467` and re-keyed on `${longitude}-${latitude}` (`:461`). Every popup render is a fresh component — no memoization concerns. Adding `title` and `visibleFields` adds zero re-render cost. The substitution happens once at click time in `BuilderMap`, not per render.

- **`label_config` migration history:** Originally created in `0002_initial_tables.py:976-978` as part of the foundational `map_layers` table — never had a separate add-column migration. So there's no historical pitfall to mirror; the cleanest analog is `2026_04_18_0002-add_notes_to_maps.py` (single nullable column add).

- **No frontend Zod schema duplication** — searched `frontend/src` for any `LabelConfig` runtime validator. Validation exists only as TypeScript type in `api.ts:682-695`. Backend Pydantic is untyped `dict | None`. **There is no client-side schema contract to extend.** UI-level validation in `PopupConfigEditor` is the *only* gate before the mutation; the locked decision to "re-validate before the mutation fires" needs to live in `PopupConfigEditor.tsx` (or a co-located util), not in a Zod schema.

- **`useLayerMapSync` mutation flow:** `handleLabelChange` (`use-layer-map-sync.ts:273-293`) uses `applyLayerUpdate` and ALSO mutates the live MapLibre map (label layer add/remove at `:286-292`). **Popup config has NO map-side effect** — no MapLibre layer to add or remove (popup is a React component, not a style layer). `handlePopupChange` should be a pure state setter: `applyLayerUpdate(layerId, (l) => ({ ...l, popup_config: config }), () => {})` — pass a no-op as the map mutator.

- **Disabled = null vs `{enabled: false}`:** the locked spec says "popup config has `enabled: false` (or the popup config is null/absent)" — both states must be handled identically. Use `popup_config?.enabled !== false` as the truthy gate (null/undefined → enabled by default-of-default). **But default behavior when `popup_config === null` should be: popup IS shown** (current behavior preserved). So the gate is: skip if `popup_config && popup_config.enabled === false`. Anything else → show.

- **`layer_config` type for `popup_config`:** TypeScript `MapLayerResponse` (`api.ts:737-760`) currently lacks `popup_config`. Add: `popup_config?: PopupConfig | null;` and define `PopupConfig` next to `LabelConfig` at `api.ts:682-695`. Same for `MapLayerInput` (`:838-851`) and `SharedLayerResponse` (`:859-881`) and `ChatMapLayer` (`:942-958`) — chat layer mirroring is a known pattern.

- **Tab type union:** `LayerEditorPanel.tsx:16` and `:28` define `'style' | 'filter' | 'labels'`. Need to extend to `'style' | 'filter' | 'labels' | 'popup'` in **5 places**: handler interface (`:16`), props interface (`:28`), tab array (`:96`), filter logic (`:97-101`), and `useBuilderLayers` state (`hooks/use-builder-layers.ts:36`).

## Files to Touch (summary, not a plan)

**Backend:** `backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py` (NEW), `backend/app/modules/catalog/maps/models.py:112` (add column), `backend/app/modules/catalog/maps/schemas.py:41-43, :149, :226` (3 schema additions), `backend/app/modules/catalog/maps/service.py:451, :625, :874` + corresponding `_build_layer_response` block (5 service-layer touchpoints), `backend/app/modules/catalog/maps/router.py:101` block.

**Frontend:** `frontend/src/types/api.ts` (PopupConfig type + 4 response/input additions), `frontend/src/lib/popup-template.ts` (NEW — extract+substitute util), `frontend/src/components/builder/PopupConfigEditor.tsx` (NEW), `frontend/src/components/builder/LayerEditorPanel.tsx` (4th tab), `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (`handlePopupChange`), `frontend/src/components/builder/hooks/use-builder-layers.ts:36` (tab union), `frontend/src/components/map/FeaturePopup.tsx:8-19` (FeatureInfo extension + render), `frontend/src/components/builder/BuilderMap.tsx:245-276` (resolve + filter hits + substitute).

**Tests:** existing pattern at `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts` and `__tests__/LayerStyleEditor.test.tsx` — mirror for popup config.

## RESEARCH COMPLETE
