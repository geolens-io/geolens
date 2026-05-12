# Milestone v1005: Builder Point Cluster Foundation

**Status:** Shipped 2026-05-12
**Audit:** passed / GO
**Phases:** 1023-1026
**Plans:** 4 / 4 complete
**Requirements:** 20 / 20 complete

## Overview

v1005 shipped native MapLibre point clustering for eligible bounded point datasets. The milestone kept the v1002-v1004 schema discipline: no migrations, no new persisted renderer tables, no deck.gl dependency, no `is_3d` writes, and no server-side clustered tile endpoint. Cluster intent is stored in existing `style_config.render_mode` / `style_config.builder` fields and falls back to normal point rendering when bounded GeoJSON is unavailable or unsupported.

## Requirements

- Cluster source eligibility: SRC-01..05 complete.
- Cluster RenderAs and MapLibre rendering: CLUS-01..06 complete.
- Compatibility and interop: COMP-01..04 complete.
- QA and closeout: QA-01..05 complete.

Full requirement archive: `.planning/milestones/v1005-REQUIREMENTS.md`.

## Phases

### Phase 1023: cluster-source-eligibility-and-geojson-contract

**Goal:** Prove when Cluster can be safely offered and wire a bounded GeoJSON source path without changing persisted schemas.

**Requirements:** SRC-01, SRC-02, SRC-03, SRC-04, SRC-05

**Completed:**

- Cluster capability visibility is derived from renderer capability metadata plus dataset geometry/source eligibility.
- Eligibility uses existing `dataset_geometry_type`, feature count, and source metadata without backend schema changes.
- Bounded GeoJSON fetching is limited to cluster layers and preserves JWT/API-key/embed-token context.
- Oversized, truncated, failed, or unsupported source loads degrade to Point with an authoring warning.
- Focused frontend tests cover eligibility, source fetching, and fallback behavior.

**Evidence:** `.planning/phases/1023-cluster-source-eligibility-and-geojson-contract/1023-VERIFICATION.md`

### Phase 1024: maplibre-point-cluster-renderer

**Goal:** Add the native MapLibre cluster renderer and keep companion-layer lifecycle consistent with existing adapters.

**Requirements:** CLUS-01, CLUS-02, CLUS-03, CLUS-04, CLUS-05

**Completed:**

- Eligible point layers expose `Cluster` through the renderer capability registry.
- Switching to Cluster writes only existing fields and stores intent under `style_config.render_mode` / `style_config.builder`.
- Map sync creates a MapLibre GeoJSON source with clustering options and stable cluster circle, cluster count, and unclustered point layers.
- Cluster companions preserve parent layer identity for map-stack and popup workflows.
- Visibility, filter, opacity, zoom range, reorder, removal, and stale cleanup apply to all cluster companion layers.

**Evidence:** `.planning/phases/1024-maplibre-point-cluster-renderer/1024-VERIFICATION.md`

### Phase 1025: cluster-builder-controls-and-authoring-polish

**Goal:** Surface the cluster renderer as a usable authoring mode without introducing new UI primitives or model fields.

**Requirements:** CLUS-06

**Completed:**

- Cluster authoring controls cover radius, max zoom, cluster color, count color, and count text size.
- Controls write only `style_config.builder`, `paint`, and `layout` fields accepted by map-layer patching.
- Cluster source options trigger source rebuilds without requiring unrelated map state changes.
- Cluster companion visibility, filter, opacity, and zoom range synchronize live.
- Builder labels and warnings are localized across supported builder locales.

**Evidence:** `.planning/phases/1025-cluster-builder-controls-and-authoring-polish/1025-VERIFICATION.md`

### Phase 1026: cluster-compatibility-and-qa-closeout

**Goal:** Prove Cluster does not regress saved maps, style JSON, viewers, or prior renderer behavior.

**Requirements:** COMP-01, COMP-02, COMP-03, COMP-04, QA-01, QA-02, QA-03, QA-04, QA-05

**Completed:**

- Backend style JSON canonicalizes cluster builder aliases.
- Style JSON export/import preserves cluster intent metadata while using explicit vector-tile Point fallback for standalone styles.
- Shared/public/embed viewer cluster layers resync after bounded GeoJSON arrives.
- Existing Point, Symbol, Heatmap, Arrow, Fill/Stroke, 3D extrusion, Raster, Hillshade, basemap, terrain, public viewer, and shared viewer behavior remained covered.
- Focused frontend/backend/i18n/lint/build/ruff checks, builder smoke, and Playwright MCP live QA passed.

**Evidence:** `.planning/phases/1026-cluster-compatibility-and-qa-closeout/1026-VERIFICATION.md`, `.planning/milestones/v1005-MILESTONE-AUDIT.md`

## Verification

- Focused frontend tests: 168 passed across builder, adapter, renderAs, map-sync, style-config, viewer, public-viewer, and shared-viewer coverage.
- Backend style JSON and migration tests: 36 passed.
- i18n check: 2 passed.
- Frontend lint: passed.
- Frontend build: passed with the pre-existing large `map-vendor` chunk warning.
- Backend ruff check and format check: passed.
- Builder smoke: 26/26 passed.
- Playwright MCP live inspection: eligible point layer switched to Cluster, saved, reloaded, persisted cluster builder config, and current-page console had 0 warnings/errors.

## Milestone Summary

**Key decisions:**

- Cluster uses native MapLibre GeoJSON clustering for bounded point datasets first.
- Large point datasets remain future server-side clustered vector-tile work.
- Cluster intent stays in existing `style_config` fields and never writes `is_3d`.
- Standalone style JSON cannot embed authenticated bounded GeoJSON; export therefore preserves intent metadata while rendering a documented Point/vector-tile fallback.

**Issues resolved:**

- Cluster source eligibility no longer depends on hidden UI assumptions.
- Cluster companion layers now follow parent lifecycle behavior.
- Cluster source option changes rebuild MapLibre sources.
- Shared/public/embed viewers now resync once bounded GeoJSON arrives.

**Issues deferred:**

- Server-side clustered vector-tile endpoint for large point datasets.
- Cluster drill-down, cluster-to-bounds camera actions, aggregate popups, and cluster legends.
- Hexbin, H3, Animated path, Point 3D extrusion, timeline playback, recipes, cross-layer filters, blend mode, basemap presets, and exact-position Add Dataset drag.

**Technical debt:**

- Frontend production build still emits the known large `map-vendor` chunk-size warning.
- GitHub Dependabot reports two high alerts on default branch; not introduced by this milestone.
