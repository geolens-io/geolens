---
quick_id: 260425-oxh
description: "layer popup config: enable/disable + custom expression with validation"
gathered: "2026-04-25"
status: ready_to_plan
---

# Quick Task 260425-oxh: Layer Popup Config — Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Task Boundary

Add a per-layer popup configuration to the Map Builder's layer config sidebar (`LayerEditorPanel`). The config must support:

1. **Enable/disable toggle** — turning popups on or off for a given layer.
2. **Custom expression** — a template string that produces a popup title/header.
3. **Visible field allowlist** — which feature properties appear below the title.
4. **Validation** — both the template expression and the chosen fields are validated against the layer's known property keys.

Scope is **frontend UI + state + persistence** plus **backend schema/storage** (mirrors the existing `label_config` pattern). Out of scope: redesigning `FeaturePopup` from scratch, building a new expression DSL, or touching public sharing/embed flows beyond surfacing the new fields if they pass through naturally.

</domain>

<decisions>
## Implementation Decisions (LOCKED)

### Expression dialect — Template strings
- The custom expression is a **plain template string** with `{property_name}` placeholders.
- Examples: `"{city}, {state}"`, `"Population: {population}"`, `"{name} — {category}"`.
- Rendering: substitute `{key}` with `feature.properties[key]` (string-coerced, missing → empty string).
- **NOT** MapLibre style expressions (no JSON arrays, no functions). Future task can add a "mode toggle" if needed.

### Popup body composition — Title + property list
- When popup is enabled AND an expression is set: render the expression's substituted output as a **title/header** above the existing FeaturePopup property list.
- Property list portion still shows feature properties (filtered by the visible-fields allowlist — see below).
- This is **additive** — the existing FeaturePopup component is layered on top of, not replaced.

### Visible fields — Allowlist via column picker
- A multi-select column picker driven by the layer's known dataset columns / feature properties.
- Storage: `visible_fields: string[] | null`.
- Semantics:
  - `null` (or omitted) → show ALL properties (current default behavior).
  - `[]` (empty array) → show NO properties (only the title from the expression).
  - `["city", "state"]` → show only those keys, **in the order specified by the user**.
- Order matters — the picker is a sortable multi-select.

### Validation UX — Live + on save
- **Live (debounced ~250ms):** as the user types in the expression field, parse `{...}` placeholders and check each against the layer's known property keys. Unknown placeholders highlighted (red border + helper text listing them).
- **On save:** re-validate before the mutation fires. Block save if invalid.
- **Server-side:** also validate in the backend schema (Pydantic) — defense in depth, but the frontend is the primary UX.
- Property-keys source: the layer's column metadata (already available via the dataset → schema endpoint or in-memory layer schema). Use the same source the existing `LabelEditor` uses for its column picker.

### Disabled fallback — Silent (no popup)
- When the popup config has `enabled: false` (or the popup config is null/absent), clicking a feature in this layer does **nothing visible** for popups.
- The layer is effectively "non-interactive for popups". Cursor change / hover effects still allowed (drawn from existing logic, not part of this task).
- Other layers on the map remain unaffected — only this layer's click → popup pipeline is suppressed.

### Claude's Discretion
- **Storage shape** — mirror the `label_config` pattern: a single JSONB column `popup_config` on `MapLayer`, with a Pydantic schema `PopupConfig { enabled, expression, visible_fields }`.
- **Migration** — single Alembic migration adds `popup_config JSONB NULL` to `MapLayer`. Default null.
- **Frontend state shape** — `MapLayerResponse.popup_config?: PopupConfig | null`.
- **UI placement** — new "Popup" tab in `LayerEditorPanel` alongside Style / Filter / Labels (4th tab).
- **Component naming** — `PopupConfigEditor.tsx` (mirrors `LabelEditor.tsx`).
- **FeaturePopup integration** — `FeaturePopup` accepts an optional `title` prop (rendered expression output) and an optional `visibleFields` prop (allowlist for property filtering). Click handler in `BuilderMap.tsx:245-276` resolves the config from the clicked layer's `popup_config` and short-circuits if `enabled === false`.

</decisions>

<specifics>
## Specific References

- **LayerEditorPanel** — `frontend/src/components/builder/LayerEditorPanel.tsx:1-160` (host component)
- **FeaturePopup** — `frontend/src/components/map/FeaturePopup.tsx:1-227` (popup renderer)
- **BuilderMap click handler** — `frontend/src/components/builder/BuilderMap.tsx:245-276` (where popup is triggered)
- **Pattern analog** — `LabelEditor` + `LabelConfig` (`frontend/src/types/api.ts:682-695` + `backend/app/modules/catalog/maps/models.py:112` + `schemas.py:41-42`)
- **Layer state hook** — `frontend/src/hooks/use-builder-layers.ts:19-66` (mutation pipeline)
- **Backend model** — `backend/app/modules/catalog/maps/models.py:83-120` (`MapLayer` class — needs new `popup_config` JSONB column)
- **Migration directory** — `backend/alembic/versions/` (latest migrations follow `YYYY_MM_DD_HHMM-slug.py`)

</specifics>

<canonical_refs>
## Canonical References

No external specs. Requirements fully captured in decisions above. Pattern is internal — mirror `label_config` end-to-end.

</canonical_refs>
