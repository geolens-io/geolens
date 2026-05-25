# Requirements: GeoLens v1026 Mapbuilder Style Reconciler

**Defined:** 2026-05-25
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v1026 Requirements

### Style Contract and Audit

- [x] **ARCH-01**: Every map-builder style mutation entry point is inventoried with code references, including manual style controls, advanced JSON, render-as switches, data-driven styles, AI chat actions, undo/history, save/reload, public viewer, embed viewer, labels, terrain, and basemap overrides.
- [x] **ARCH-02**: The milestone defines canonical style mutation semantics for patch, replace, clear, reset, and layer rebuild operations, with AI `set_style` semantics explicitly classified.
- [x] **ARCH-03**: Each adapter declares the paint/layout/style properties it owns, including companion layers such as fill outlines, labels, cluster sublayers, arrow layers, hillshade/raster layers, and fill-extrusion surfaces.
- [x] **ARCH-04**: A regression matrix is documented for stale-style transitions, including gradient-to-solid, data-driven-to-flat, dashed-to-solid, outline-off/on, label-off/on, extrusion-off, heatmap/cluster/symbol render-mode swaps, and AI style edits.

### Shared Reconciler

- [x] **RECON-01**: A shared style reconciler applies changed owned paint/layout properties and clears removed owned properties from live MapLibre layers.
- [x] **RECON-02**: The reconciler filters invalid cross-geometry paint/layout keys, keeps custom builder metadata out of MapLibre paint/layout calls, and preserves expression values without flattening or cloning where identity matters.
- [x] **RECON-03**: Paint-only style changes do not re-add sources or refetch tiles; layer rebuilds are limited to render-mode/source-type transitions that require them.
- [x] **RECON-04**: Focused unit tests cover set, no-op, clear, invalid-key filtering, expression preservation, companion-layer ownership, and MapLibre error isolation.

### Adapter Migration

- [x] **ADAPT-01**: Line, fill, circle, and fill-extrusion style sync paths use the shared reconciler instead of one-off additive paint updates.
- [x] **ADAPT-02**: Heatmap, cluster, raster, and hillshade style sync paths use the shared reconciler or a documented adapter-specific equivalent where MapLibre requires source/layer rebuilds.
- [x] **ADAPT-03**: Label, outline, arrow, and cluster companion layers reconcile visibility, paint, layout, filters, and deletion atomically with their parent layer.
- [x] **ADAPT-04**: One-off stale-property cleanup paths are removed or reduced to adapter-owned-property declarations, with regression tests replacing bug-specific cleanup tests where practical.

### UI and AI Style Actions

- [x] **STYLE-01**: High-risk manual style controls emit through central style mutation helpers or typed transactions rather than ad hoc raw paint/config object surgery.
- [x] **STYLE-02**: Data-driven style enable/disable and render-as mode switches preserve unrelated style fields while clearing stale owned properties from the previously active mode.
- [x] **STYLE-03**: Advanced JSON remains an intentional full paint/layout replace path, with validation and clear semantics documented separately from normal patch-style controls.
- [x] **AI-01**: Chat `set_style` applies patch semantics against the current layer style instead of replacing the full paint object unless the action explicitly requests replacement.
- [x] **AI-02**: AI chat has an explicit way to clear stale style properties, either through typed actions or clear lists, and the backend tool schema/prompt describes that contract.
- [x] **AI-03**: Backend chat validation and generated API types stay aligned with any `ChatAction` schema changes, including MapLibre paint validation and clear/replace semantics.
- [x] **AI-04**: Chat undo/history restores style changes through the same reconciler path as manual UI changes and preserves paint/style_config parity.

### Persistence and Viewer Parity

- [x] **PERSIST-01**: Saved map JSON stores the canonical post-reconciliation `paint`, `layout`, `style_config`, `label_config`, and opacity state without persisting transient reconciler metadata.
- [x] **PERSIST-02**: Save/reload round trips preserve visual output for all migrated style modes and do not resurrect stale properties.
- [x] **VIEW-01**: Public viewer and embed viewer render reconciled saved styles consistently with the builder for migrated layer types.
- [x] **VIEW-02**: Style JSON export/import remains compatible with reconciled layer styles and rejects or sanitizes invalid stale properties consistently.

### Verification and Close Gate

- [x] **VERIFY-01**: Focused frontend tests cover adapter reconciliation, manual UI style transitions, AI chat style actions, save/reload normalization, and viewer rendering helpers.
- [x] **VERIFY-02**: Playwright MCP verifies the ADK 3D Relief map after migration, including Hiking trails gradient-to-solid, representative data-driven-to-flat, label toggle, and render-mode switch flows.
- [x] **VERIFY-03**: Frontend `npm run test`, `npm run typecheck`, and `npm run lint` pass for the touched builder/style areas.
- [x] **VERIFY-04**: Browser console and failed-network capture for the target map shows zero unexpected errors/warnings after the reconciler migration.
- [x] **VERIFY-05**: CHANGELOG and phase summaries document migration scope, AI-chat impact, accepted limitations, and any follow-up requirements.

## Future Requirements

### Follow-Up Architecture

- **STYLE-FU-01**: Consider a fuller typed style transaction domain model after the reconciler milestone, if raw paint/config manipulation remains noisy in editor components.
- **STYLE-FU-02**: Consider moving backend and frontend MapLibre paint-property allowlists to a generated shared source to avoid schema drift.

### CI Infrastructure

- **CI-01-v1026**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This rolling external blocker remains outside the style reconciler invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Rebuilding the entire map builder UI | v1026 hardens style mutation semantics and live MapLibre reconciliation, not the editor information architecture. |
| Redesigning AI chat UX | AI chat is in scope only where style actions mutate map styles or require schema/tool contract changes. |
| New cartographic controls unrelated to reconciliation | New styling features should wait until the mutation pipeline is stable. |
| Replacing MapLibre or the imperative layer sync model | Existing MapLibre imperative integration is intentional for vector tiles; this milestone makes that integration more deterministic. |
| Closing the GitHub Actions billing blocker | CI live-verify remains an external operator prerequisite carried forward from v1023. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ARCH-01 | Phase 1112 | Complete |
| ARCH-02 | Phase 1112 | Complete |
| ARCH-03 | Phase 1112 | Complete |
| ARCH-04 | Phase 1112 | Complete |
| RECON-01 | Phase 1113 | Complete |
| RECON-02 | Phase 1113 | Complete |
| RECON-03 | Phase 1113 | Complete |
| RECON-04 | Phase 1113 | Complete |
| ADAPT-01 | Phase 1114 | Complete |
| ADAPT-02 | Phase 1114 | Complete |
| ADAPT-03 | Phase 1114 | Complete |
| ADAPT-04 | Phase 1114 | Complete |
| STYLE-01 | Phase 1115 | Complete |
| STYLE-02 | Phase 1115 | Complete |
| STYLE-03 | Phase 1115 | Complete |
| AI-01 | Phase 1115 | Complete |
| AI-02 | Phase 1115 | Complete |
| AI-03 | Phase 1115 | Complete |
| AI-04 | Phase 1115 | Complete |
| PERSIST-01 | Phase 1116 | Complete |
| PERSIST-02 | Phase 1116 | Complete |
| VIEW-01 | Phase 1116 | Complete |
| VIEW-02 | Phase 1116 | Complete |
| VERIFY-01 | Phase 1117 | Complete |
| VERIFY-02 | Phase 1117 | Complete |
| VERIFY-03 | Phase 1117 | Complete |
| VERIFY-04 | Phase 1117 | Complete |
| VERIFY-05 | Phase 1117 | Complete |

**Coverage:**
- v1026 requirements: 28 total, 28 complete
- Mapped to phases: 28
- Unmapped: 0

---
*Requirements defined: 2026-05-25*
*Last updated: 2026-05-25 after Phase 1117*
