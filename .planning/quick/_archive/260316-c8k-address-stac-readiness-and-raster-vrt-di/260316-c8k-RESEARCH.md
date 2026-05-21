# Quick Task 260316-c8k: STAC Readiness & Raster/VRT Discovery UX - Research

**Researched:** 2026-03-16
**Domain:** STAC compliance gap analysis + catalog type filtering UX
**Confidence:** HIGH

## Summary

GeoLens has strong STAC foundations already in place from the 260316-bgd quick task: a `DatasetAsset` model with STAC-aligned fields (key, href, media_type, roles, size_bytes), a `RasterAsset.to_stac_properties()` method producing `proj:epsg`, `proj:wkt2`, `proj:shape`, `gsd`, and `bands`, plus a backfill migration populating existing raster/VRT assets. The catalog already has `record_type` filtering in both the backend search service and the frontend search store.

For the type filter chips: the frontend **already has** a ToggleGroup with All/Vector/Raster chips in `FilterPanel.tsx`. The gap is that VRT is missing as a filter option and the current chips only pass single `record_type` values. Adding VRT requires either a fourth chip value or mapping "Raster" to include both `raster_dataset` and `vrt_dataset`.

**Primary recommendation:** (1) Add VRT as a fourth toggle chip, (2) audit and document STAC 1.1.0 gaps in a structured gap analysis, (3) no API changes needed -- `record_type` filtering already works.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Audit & document only: produce a gap analysis of what exists vs. what's needed for STAC 1.1 compliance, with prioritized next steps
- No new STAC endpoints or API changes in this task
- Existing infrastructure: DatasetAsset model, to_stac_properties(), backfill migration
- Type filter chips above search results (All / Vector / Raster / VRT)
- Mixed results by default, user narrows by type
- Minimal UI change, leverages existing record_type field
- Explicit user-driven chips only -- no smart defaults or auto-filtering
- "All" selected by default
- Simple, predictable behavior

### Claude's Discretion
- None -- all areas discussed

### Deferred Ideas (OUT OF SCOPE)
- None explicitly listed
</user_constraints>

## Current State Analysis

### What Already Exists

**Backend (record_type filtering):**
- `Record.record_type` column: constrained to `vector_dataset`, `raster_dataset`, `vrt_dataset`, `map`, `service`, `collection`
- `search_datasets()` in `backend/app/search/service.py` line 292: `if record_type: stmt = stmt.where(Record.record_type == record_type)` -- exact match filter
- Search router (`/search/datasets` and `/collections/datasets/items`) both accept `record_type` query param
- OGC record output includes `record_type` in properties

**Frontend (type filter chips -- ALREADY PARTIALLY BUILT):**
- `FilterPanel.tsx` lines 268-285: desktop ToggleGroup with `all`, `vector_dataset`, `raster_dataset`
- `FilterPanel.tsx` lines 401-418: mobile ToggleGroup (same values)
- `search-store.ts`: `record_type` field already in state, wired to `toParams()` and `restoreParams()`
- `DatasetCard.tsx` line 19: VRT detection via `properties.record_type === 'vrt_dataset'`
- Missing: `vrt_dataset` chip in the ToggleGroup

**STAC-aligned models:**
- `DatasetAsset` model: `key`, `href`, `media_type`, `title`, `description`, `roles` (ARRAY), `size_bytes`
- `RasterAsset.to_stac_properties()`: produces `proj:epsg`, `proj:wkt2`, `proj:shape`, `gsd`, `bands`
- Backfill migration populates `dataset_assets` from existing `raster_assets`

### STAC 1.1.0 Gap Analysis

| STAC 1.1.0 Requirement | GeoLens Status | Gap | Priority |
|------------------------|----------------|-----|----------|
| **Item `type`** = "Feature" | Present in `dataset_to_ogc_record()` | None | -- |
| **Item `stac_version`** = "1.1.0" | Missing | Add literal to record output | HIGH |
| **Item `id`** (unique string) | Present (`dataset.id` UUID) | None | -- |
| **Item `geometry`** (GeoJSON or null) | Present (`spatial_extent` -> GeoJSON) | None | -- |
| **Item `bbox`** (array of numbers) | Missing at item level | Compute from geometry, add to output | HIGH |
| **Item `properties.datetime`** (RFC 3339 or null) | Missing (have `created`/`updated` but not `datetime`) | Add `datetime` from `temporal_start` or null | HIGH |
| **Item `links`** (array) | Present with self/collection/root | Need `type` on all links | LOW |
| **Item `assets`** (object keyed by string) | Missing from record output | Query `DatasetAsset` rows, format as STAC assets dict | MEDIUM |
| **Asset `href`** (required) | Present in `DatasetAsset.href` | None | -- |
| **Asset `type`** (media type, strongly recommended) | Present in `DatasetAsset.media_type` | None | -- |
| **Asset `roles`** (array) | Present in `DatasetAsset.roles` | None | -- |
| **Collection `type`** = "Collection" | Missing (have `id`, `title`, etc.) | Add literal | MEDIUM |
| **Collection `stac_version`** | Missing | Add literal | MEDIUM |
| **Collection `license`** | Partial (`record.license` exists but not at collection level) | Aggregate or set default | LOW |
| **Catalog root** with `type` = "Catalog" | Missing (OGC landing page exists) | Add STAC fields to landing page | LOW |
| **STAC conformance URIs** in `/conformance` | Missing (only OGC URIs present) | Add `https://api.stacspec.org/v1.0.0/core` etc. | MEDIUM |
| **proj extension** fields | Present via `to_stac_properties()` | None | -- |
| **bands** (STAC 1.1 common metadata) | Present in `to_stac_properties()` | None | -- |

### Key Observations

1. **The OGC record output is very close to STAC Item format** -- both are GeoJSON Features. The main gaps are three required fields: `stac_version`, `bbox`, and `properties.datetime`.

2. **DatasetAsset model is STAC-ready** -- the schema was designed to align with STAC assets (key, href, media_type, roles). The gap is that record output doesn't include them yet.

3. **`record_type` filtering works end-to-end** for single values. The user wants four chips: All / Vector / Raster / VRT. Backend already handles `record_type=vrt_dataset` correctly.

## Implementation Approach

### 1. Add VRT Chip to FilterPanel

Minimal change: add a fourth `ToggleGroupItem` with value `vrt_dataset` to both desktop and mobile ToggleGroups in `FilterPanel.tsx`. The backend already filters by `record_type=vrt_dataset`.

```tsx
// Add after raster_dataset ToggleGroupItem
<ToggleGroupItem value="vrt_dataset" className="text-xs px-2.5 h-7">
  {t('filters.vrt', { defaultValue: 'VRT' })}
</ToggleGroupItem>
```

Also add i18n key `filters.vrt` to all four locale files.

### 2. STAC Gap Analysis Document

Create a structured gap analysis as a markdown document. No code changes -- just documentation of:
- What GeoLens already implements (with STAC field mapping)
- What's missing for STAC 1.1.0 compliance
- Prioritized roadmap for closing gaps
- Which gaps are quick wins vs. require significant work

### 3. Conditional Geometry Filter Visibility

Current code hides geometry_type filter when `recordType === 'raster_dataset'`. Should also hide for `vrt_dataset`:

```tsx
{recordType !== 'raster_dataset' && recordType !== 'vrt_dataset' && (
  // geometry type filter
)}
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| STAC spec compliance checking | Custom validation | Reference STAC spec directly | Spec is well-documented, no library needed for audit |
| Type filter state management | Custom state | Existing zustand search-store | Already wired, just add values |

## Common Pitfalls

### Pitfall 1: ToggleGroup Empty Selection
**What goes wrong:** shadcn/ui ToggleGroup with `type="single"` returns empty string when user clicks the active item, deselecting all.
**How to avoid:** The current code already handles this by mapping `'all'` to empty string and vice versa. Same pattern works with VRT added.

### Pitfall 2: record_type Exact Match vs. Multi-Value
**What goes wrong:** Backend `record_type` filter is exact match (`==`). If we wanted "Raster" to include both raster_dataset AND vrt_dataset, we'd need backend changes.
**How to avoid:** User decision is four separate chips (All/Vector/Raster/VRT), so exact match is correct. Each chip maps to one record_type value.

### Pitfall 3: i18n Key Gaps
**What goes wrong:** Adding VRT chip without updating all four locale files causes fallback-to-default in non-English locales.
**How to avoid:** Update en, es, fr, de locale files for `filters.vrt`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest + React Testing Library (frontend), pytest (backend) |
| Quick run command | `cd frontend && npx vitest run --reporter=verbose` |
| Full suite command | `cd backend && python -m pytest -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STAC-AUDIT | Gap analysis document produced | manual-only | N/A -- documentation output | N/A |
| VRT-CHIP | VRT filter chip appears and filters correctly | unit | `cd frontend && npx vitest run src/components/search -t "VRT"` | Wave 0 |
| TYPE-FILTER | All four chips filter search results | unit | `cd frontend && npx vitest run src/components/search -t "record_type"` | Wave 0 |

### Wave 0 Gaps
- [ ] FilterPanel test for VRT chip rendering and click behavior -- no existing FilterPanel test file found
- [ ] i18n assertions for `filters.vrt` key across all locales

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `backend/app/search/router.py`, `backend/app/search/service.py`, `backend/app/raster/models.py`, `backend/app/datasets/models.py`
- Codebase inspection: `frontend/src/components/search/FilterPanel.tsx`, `frontend/src/stores/search-store.ts`
- Codebase inspection: `backend/tests/test_stac_asset_model.py`
- STAC spec: https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md (STAC 1.1.0 item requirements)

### Secondary (MEDIUM confidence)
- STAC 1.1.0 spec knowledge from training data -- field requirements verified against existing codebase implementation

## Metadata

**Confidence breakdown:**
- Current state analysis: HIGH -- direct codebase inspection
- STAC gap analysis: HIGH -- well-documented spec, verified against code
- UI implementation: HIGH -- existing pattern already in FilterPanel, just adding one more value

**Research date:** 2026-03-16
**Valid until:** 2026-04-16 (stable domain)
