# Phase 1149: Layer Label Indicator - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped); grounded in the v1033 live-MCP audit (finding F4).

<domain>
## Phase Boundary

Add a derived indicator to builder layer rows so a layer with labels configured is visually distinct from one without. Confirmed gap in the live audit (F4): the "ADK 46er peaks" row (labels on) and "Hiking trails" row (labels off) are structurally identical — no label affordance in the list. Requirement: LABEL-01.

Pure derivation — NO new persisted state. Mirror the existing v1011 `SublayerConfigIndicators` pattern (which already renders a "Labels" indicator for basemap sublayers).
</domain>

<decisions>
## Implementation Decisions

### Locked (from code inspection)
- **"Labels enabled" predicate is `!!layer.label_config?.column`.** `LabelConfig` (`api.ts:758`) has NO `enabled` field; labels render iff a `column` is set. This is the SAME predicate used at `SublayerConfigIndicators.tsx:43` and `map-sync.ts:795` (`label_config?.column && !isHeatmap && !isSymbol`). Use exactly this predicate so the indicator matches what actually renders on the map.
- **Heatmap/symbol exception:** `map-sync.ts:795` suppresses labels for heatmap and symbol render modes even when a column is set. The indicator SHOULD match real render behavior — suppress the indicator when the layer's render_mode is `heatmap` or `symbol` (i.e. labels won't actually draw). Keep this consistent with the map-sync gate.
- **Target component:** `frontend/src/components/builder/StackRow.tsx` — the layer row. It's a 6-col grid (`grid-cols-[16px_14px_22px_22px_1fr_22px]`: caret, grip, eye, type-icon, name(1fr), kebab). `useTranslation('builder')`.
- **Placement (Claude's discretion):** prefer a small, unobtrusive glyph/badge inside the name cell (cell 5) trailing the name, OR a subtle marker near the type icon — must not break the fixed grid or truncation of long names. The existing `TypeIcon` already shows per-row derived glyphs (▦/⛰/◬ for DEM modes), so a small derived label glyph is consistent precedent. Use a Lucide icon (e.g. `Type` or `Tag`) or a compact "A" badge — pick what reads as "labels" and matches the row's muted-foreground styling.
- **A11y:** the indicator needs an accessible name (aria-label or title) like "Labels on: {column}" — not just a decorative glyph. If it's purely informative (not interactive), `aria-hidden` on the glyph + a visually-hidden/`title` text, or a `title` attribute, is acceptable; match how SublayerConfigIndicators does it.
- **i18n:** add a `builder` namespace key (e.g. `stackRow.labelsIndicator`) with `defaultValue`, and add parity entries in all four locales: `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (verify exact path/namespace file). i18n parity is gated by the repo's i18n test (`npm run test:i18n` / the 2/2 i18n gate).

### Out of scope
Render-mode fix (1148, done), point-control consolidation + hillshade guard + cache bound (1150), MCP close-gate (1151). Do not alter label *rendering* (map-sync) — only add the list indicator.
</decisions>

<code_context>
## Existing Code Insights

- `frontend/src/components/builder/StackRow.tsx` — row component + `TypeIcon` (per-row derived glyph precedent at l.58-98); grid at l.220; name cell l.311-348.
- `frontend/src/components/builder/SublayerConfigIndicators.tsx` — the v1011 pure-derivation pattern; "Labels — label_config.column set" at l.12 + l.43. Reuse its visual/derivation approach.
- `frontend/src/types/api.ts:758` — `LabelConfig` (no `enabled`; `column` is the signal). `MapLayerResponse.label_config` at l.1116/1204.
- `frontend/src/components/builder/map-sync.ts:795` — authoritative label-render gate (`label_config?.column && !isHeatmap && !isSymbol`).
- i18n locales dir: `frontend/src/i18n/locales/{en,de,es,fr}/` (confirm the `builder` namespace file name).
- Tests: `frontend/src/components/builder/__tests__/StackRow*.test.tsx` (add one) and/or `UnifiedStackPanel.test.tsx`; `SublayerConfigIndicators.test.tsx` for reference.
</code_context>

<specifics>
## Specific Ideas

- LABEL-01 acceptance: a row whose `label_config.column` is set (and render_mode not heatmap/symbol) shows the indicator; a row without labels does not. Verified live at 1151 on Map A ("ADK 46er peaks" shows it; "Hiking trails" does not).
- Add a unit/RTL test asserting the indicator is present for a labeled layer fixture and absent for an unlabeled one (positive + negative assertion).
- i18n: 4-locale parity; a11y: accessible name present.
</specifics>

<deferred>
## Deferred Ideas
None — discuss phase skipped.
</deferred>
