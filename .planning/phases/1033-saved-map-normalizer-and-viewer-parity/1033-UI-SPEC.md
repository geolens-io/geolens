---
phase: 1033
slug: saved-map-normalizer-and-viewer-parity
status: draft
shadcn_initialized: true
preset: new-york / neutral base / OKLCH tokens in src/index.css
created: 2026-05-13
---

# Phase 1033 — UI Design Contract

> Visual and interaction contract for Phase 1033: saved-map-normalizer-and-viewer-parity.
>
> **Parity-only phase.** No new design surfaces are introduced. The sidebar continues
> to render as the existing six-section MapStackPanel until Phase 1034 ships. This
> contract documents what MUST NOT REGRESS across the four viewer surfaces
> (builder, public, shared, embed) as the normalizer lands.

---

## Phase Scope Note

Phase 1033 is a foundational data-layer phase. Its only visible effect is that
legacy six-section saved maps CONTINUE to render correctly — no layers missing,
no console errors — after the normalizer module replaces the raw saved-map read.

All new design surfaces (unified stack rows, LayerEditorPanel flyout, basemap-as-group,
DEM render-mode, settings affordance, empty state) are owned by Phases 1034–1037.
Sketch fidelity, a11y, i18n, and UAT are owned by Phase 1038.

Do NOT re-specify typography, spacing, or color decisions for this phase —
they are inherited from the existing live `frontend/src/index.css` tokens
and the `sketch-findings-geolens` skill, which are locked for downstream phases.

---

## Design System

| Property | Value | Source |
|----------|-------|--------|
| Tool | shadcn (new-york style) | `frontend/components.json` |
| Preset | OKLCH token set, neutral base | `frontend/src/index.css` lines 29–79 |
| Component library | Radix UI (via shadcn) | `components.json` |
| Icon library | Lucide | `components.json` → `iconLibrary: lucide` |
| Font | IBM Plex Sans Variable / IBM Plex Mono | `frontend/src/index.css` line 258–259 |

---

## Spacing Scale

Inherited — no change in Phase 1033. Locked by downstream phases 1034–1037.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, inline padding |
| sm | 8px | Compact element spacing |
| md | 16px | Default element spacing |
| lg | 24px | Section padding |
| xl | 32px | Layout gaps |
| 2xl | 48px | Major section breaks |
| 3xl | 64px | Page-level spacing |

Exceptions: none for Phase 1033.

---

## Typography

Inherited — no change in Phase 1033. Locked by downstream phases.

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 16px (1rem) | 400 | 1.5 |
| Label | 14px (0.875rem) | 400 | 1.4 |
| Caption / badge | 12px (0.75rem) | 400 | 1.3 |
| Heading | 20px | 600 | 1.2 |

Source: `frontend/src/index.css` lines 17–19, 431, 438, 482.

---

## Color

Inherited — no change in Phase 1033. Locked tokens from `frontend/src/index.css`.

| Role | OKLCH Value | Usage |
|------|-------------|-------|
| Dominant (60%) | `oklch(0.985 0.003 85)` — `--background` | Map canvas background, warm atlas-paper surfaces |
| Secondary (30%) | `oklch(0.97 0.003 85)` — `--secondary` / `--surface-2` | Sidebar panel, card backgrounds |
| Accent (10%) | `oklch(0.55 0.18 250)` — `--primary` | Selected row highlight, active controls, focus ring |
| Destructive | `oklch(0.577 0.245 27.325)` — `--destructive` | Delete actions only |

Accent reserved for: selected layer row highlight, active tab indicators, focus ring
on interactive elements. Not used for decorative elements.

Phase 1033 introduces no new color surfaces. The normalizer is a data transform;
it touches no rendered color tokens.

---

## Parity Contract (Core of This Phase)

This section replaces the standard "Copywriting Contract" for Phase 1033 because
the phase has no new UI copy, CTAs, or empty states. Instead, the contract
specifies what existing visual surfaces must remain pixel-equivalent before and
after the normalizer ships.

### Viewer Surfaces That Must Not Regress

| Viewer | Entry Point | Must Pass |
|--------|-------------|-----------|
| Builder | `MapStackPanel.tsx` + `BuilderMap` | All six legacy sections render; no missing layers |
| Public viewer | `frontend/src/components/viewer/` | Same layer set as builder, pixel-equivalent map output |
| Shared viewer | Shared-token viewer path | Same layer set, no missing auth-gated layers |
| Embed viewer | Embed token viewer path | Same layer set, no iframe console errors |

### Visual Artifacts That Must Be Preserved

For any legacy six-section saved map `{ surface, relief, basemap, data, labels, interactions }`:

| Artifact | Preservation Rule |
|----------|-------------------|
| Basemap tile layer | Renders at correct z-order; basemap style URL unchanged |
| Vector data layers | All `data` section layers appear; paint/layout props preserved |
| Raster data layers | All raster sources appear; opacity/resampling props preserved |
| DEM / terrain layers | `surface` + `relief` sections: terrain config applied; hillshade paint preserved |
| Label layers | `labels` section layers appear; text layout props preserved |
| Interaction widgets | `interactions` section settings applied; no widget config lost |
| Basemap label toggle | `show_basemap_labels` / `basemap_config.label_mode` honored |
| Cluster layers | Server-side and bounded cluster adapter companion layers preserved |
| Layer opacity | Per-layer `opacity` value preserved across normalizer transform |
| Layer z-order | `sort_order` preserved; map layer stack order is invariant |

### No New Network Calls Allowed

The normalizer MUST NOT introduce new tile or source requests beyond what the
legacy loader produced. The following must be byte-equivalent after normalization:

- Tile URL patterns (`/tiles/vector/...`, `/tiles/raster/...`, `/tiles/clusters/...`)
- Auth token pass-through (JWT / API-key / embed-token)
- GeoJSON source URLs for bounded cluster layers

If the normalizer must restructure a source URL, the tile endpoint and query
string must be identical to what the legacy path would have produced.

### Console Error Budget

After the normalizer ships, the following is the allowed console state for any
legacy saved map opened in any viewer:

| Console Level | Budget |
|---------------|--------|
| Error | 0 (zero, hard requirement) |
| Warning | 0 (zero, hard requirement — same as current baseline) |
| Info / debug | No constraint |

This matches the v1007 Release Hygiene baseline: the live page console was
confirmed clean (zero warnings, zero errors) as of Phase 1032.

---

## Regression Fixture Set

The canonical regression gate for Phase 1033 is the saved-map compatibility
fixture committed at `d2c5c99c` (`test(1000-02): lock saved map stack compatibility`).

These fixtures must:
1. Pass against the normalized loader without any schema migration to stored data.
2. Produce the same MapLibre source + layer set as the pre-normalizer legacy loader.
3. Round-trip through save → reload with no data loss.

### Viewer Exercise Sequence

For each legacy fixture, the verification sequence is:

1. Open in builder → confirm all layers present, no console errors.
2. Save (optional re-save not required for legacy fixtures).
3. Open public viewer → assert layer count equals builder.
4. Open shared viewer (with shared token) → assert layer count equals builder.
5. Open embed viewer (with embed token) → assert layer count equals builder.
6. Save a new map under the unified shape → reload → confirm lossless round-trip.

---

## Copywriting Contract

Phase 1033 introduces no new user-visible copy. No new CTAs, empty states,
error messages, or destructive actions are introduced.

| Element | Copy | Note |
|---------|------|------|
| Primary CTA | — | No new CTAs in this phase |
| Empty state | — | Existing MapStackPanel empty state unchanged |
| Error state | — | Existing error handling unchanged |
| Destructive confirmation | — | No destructive actions in this phase |

Any normalizer-level errors (e.g., unrecognized legacy shape) must be caught
and logged at `console.warn` level only — never thrown as unhandled exceptions
and never surfaced as visible UI errors. Fallback: render the layer using
best-effort defaults rather than omitting it.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Existing installed components only (no new blocks) | not required |
| Third-party | none | not applicable |

Phase 1033 adds no new shadcn components or third-party registry blocks.
The normalizer is a TypeScript module, not a UI component.

---

## Downstream Phase Lock

The following design decisions are explicitly DEFERRED to later phases.
Phase 1033 must not implement, reference, or stub any of these:

| Decision | Owned By |
|----------|----------|
| Unified stack row anatomy (drag · visibility · type-icon · name · opacity · kebab) | Phase 1034 |
| LayerEditorPanel flyout (380px, side-by-side) | Phase 1034 |
| Basemap-as-group (`⊞` glyph, sublayer expansion) | Phase 1035 |
| User folder groups (`▸` glyph) | Phase 1035 |
| DEM render-mode selector (image / hillshade / terrain) | Phase 1035 |
| `⚙ Settings` affordance (terrain, widgets, projection) | Phase 1036 |
| Empty state catalog entry experience | Phase 1037 |
| Sketch fidelity verification | Phase 1038 |
| Accessibility + keyboard nav | Phase 1038 |
| i18n keys for new copy | Phase 1038 |
| Playwright MCP UAT | Phase 1038 |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS (no new copy — parity-only phase)
- [ ] Dimension 2 Visuals: PASS (no new surfaces — regression budget is zero errors)
- [ ] Dimension 3 Color: PASS (inherited tokens only — no change)
- [ ] Dimension 4 Typography: PASS (inherited tokens only — no change)
- [ ] Dimension 5 Spacing: PASS (inherited scale — no change)
- [ ] Dimension 6 Registry Safety: PASS (no new components or third-party blocks)

**Approval:** pending
