# Phase 1141: Fill-Pattern Editor Control - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); UI guidance baked in (control mirrors the existing IconPicker — no separate ui-phase).

<domain>
## Phase Boundary

Add a fill-pattern authoring control to the fill-render-mode editor (`FillEditor`), letting the user apply a pattern from a **curated built-in set** to a fill layer (and clear back to a solid fill).

Requirement: **EDITOR-FILL-01** — fill-pattern (pattern selection flow; sprite-backed) for fill layers.

</domain>

<decisions>
## Implementation Decisions

### Locked scope decision (from v1031 REQUIREMENTS.md sizing escape-hatch)
- **Built-in curated pattern set ONLY this phase.** Do NOT build arbitrary user sprite upload / sprite storage+serving backend — that is explicitly deferred to a Future requirement if it balloons. Ship a small curated set of tileable patterns (e.g. hatch, cross-hatch, diagonal lines, dots/grid) plus a "None" (solid) option.

### Known constraints (v1031 HARD INVARIANTS — do NOT violate)
- Feature-add on the v1026 style-reconciler + v1027 controller/action/sync substrate and the v1010/v1030 per-render-mode editor split. The new control extends `FillEditor` consistently with its existing controls.
- **Behavior preservation (success criterion):** existing fill controls (fill color, fill opacity, extrusion hint) MUST remain unaffected. A fill layer with no pattern selected renders exactly as today.
- **No architecture rewrites:** no new files >500 LOC; no rename of >3 exported symbols; no controller/action-boundary widening.
- `fill-pattern` is a REAL MapLibre fill paint property (unlike the v1140 builder-private `_*` keys) — it should flow through the fill-adapter's owned-paint contract the v1026 way (NOT a private companion-layer mechanism). Confirm how `fill-adapter.ts` owns paint and add `fill-pattern` there.

</decisions>

<code_context>
## Existing Code Insights (analogs — READ THESE during planning)

- **`frontend/src/components/builder/IconPicker.tsx`** — the established picker UI (grid/popover of selectable swatches). The fill-pattern picker should MIRROR this component's structure, tokens, and interaction (selection ring, "none" affordance). Do not invent a new picker idiom.
- **`frontend/src/components/builder/layer-adapters/symbol-adapter.ts`** — how symbol/icon layers register sprite images with the map (`map.addImage` / sprite handling). The pattern images must be registered in the MapLibre image registry the same way before `fill-pattern` can reference them by name.
- **`frontend/src/components/builder/BuilderMap.tsx`** — map image/sprite registration lifecycle (where addImage is wired); ensure built-in patterns are registered once and survive style reloads.
- **`frontend/src/components/builder/layer-adapters/fill-adapter.ts`** — where fill paint is owned/synced; `fill-pattern` paint goes here. Confirm the owned-paint set + defaults pattern (v1026 contract) and how clearing the pattern restores solid fill (fill-color path).
- **`frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx`** (or equivalent per-render-mode child) — where the new "Fill Pattern" section/control mounts.

## MapLibre note
`fill-pattern` requires the referenced image to exist in the map's image registry (`map.addImage(name, image)`) or sprite. Built-in patterns can be generated to a canvas/ImageData (tileable) or bundled as small PNGs and registered at map-load. When `fill-pattern` is set, MapLibre renders the pattern in place of solid `fill-color`; `fill-opacity` still applies. Clearing the pattern (set to undefined/none) restores the solid `fill-color` render.

</code_context>

<specifics>
## Specific Ideas

- UI: a "Fill Pattern" control in FillEditor mirroring IconPicker — a popover/grid of curated pattern swatches + a "None" (solid) option as the default/clear state.
- Patterns registered once on map load (idempotent, StrictMode-safe — see the v1010.2 `autoCapturedMapIds` Set pattern / use-quicklook patterns for module-level guards if needed) and re-registered on style reload.
- Selecting a pattern writes `fill-pattern` (owned paint); selecting "None" clears it back to solid fill.
- New i18n keys in ALL FOUR locales (en/de/es/fr) — `resources.test.ts` parity.
- Focused vitest for the picker + fill-adapter pattern handling; `tsc -b --noEmit` clean.

</specifics>

<deferred>
## Deferred Ideas

- Custom user sprite/pattern UPLOAD (storage + serving backend) — Future requirement (only if the built-in set proves insufficient). Out of scope this phase.
- Per-pattern color tinting / scale controls — out of scope unless trivially free with the built-in set.

</deferred>
