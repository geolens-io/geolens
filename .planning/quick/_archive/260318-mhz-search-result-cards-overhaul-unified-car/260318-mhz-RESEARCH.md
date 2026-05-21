# Search Result Cards Overhaul - Research

**Researched:** 2026-03-18
**Domain:** Frontend search result card components + backend API data availability
**Confidence:** HIGH

## Summary

The current search page uses two separate card components: `DatasetCard` for vector/raster/VRT records and `CollectionSearchCard` for collections. These have completely different layouts, prop interfaces, and visual weight. DatasetCard is a full horizontal card with quicklook preview, metadata badges, provenance, and tags. CollectionSearchCard is a minimal compact card with just title, description, dataset count, and a folder icon. There is no unified component hierarchy.

**Primary recommendation:** Create a single `SearchResultCard` component with a shared layout shell (title, description, type badge, preview area, provenance) and type-specific metadata slots. Most data is already available in API responses; only VRT-specific fields (vrt_type, source_count) need to be added to the search response.

## Current Component Architecture

### Existing Components

| Component | File | Used For | Layout |
|-----------|------|----------|--------|
| `DatasetCard` | `components/search/DatasetCard.tsx` | vector, raster, VRT | Horizontal card: metadata left, quicklook/bbox right (hidden on mobile) |
| `CollectionSearchCard` | `components/search/CollectionSearchCard.tsx` | collections | Compact row: folder icon + title + dataset count badge |
| `DatasetCardSkeleton` | `components/search/DatasetCardSkeleton.tsx` | loading state | Matches DatasetCard layout |
| `RecordTypeBadge` | `components/search/RecordTypeBadge.tsx` | all types | Colored badge with icon per type (blue/emerald/violet/amber) |
| `QualityBadge` | `components/search/QualityBadge.tsx` | datasets | Tooltip-wrapped score pill |
| `BBoxPreview` | `components/layout/BBoxPreview.tsx` | fallback when no quicklook | SVG world map with bbox rectangle |

### Rendering Logic (SearchPage.tsx)

```tsx
// Line 139-151 of SearchPage.tsx
data.features.map((feature) =>
  feature.properties.record_type === 'collection'
    ? <CollectionSearchCard key={...} id={...} title={...} description={...} datasetCount={...} />
    : <DatasetCard key={...} feature={feature} />
)
```

Collections are passed individual props extracted from the feature; datasets get the full OGC feature object.

## Available API Data per Record Type

### OGCRecordProperties (from search endpoint)

| Field | Vector | Raster | VRT | Collection | Notes |
|-------|--------|--------|-----|------------|-------|
| `title` | Y | Y | Y | Y (as `name`) | |
| `description` | Y | Y | Y | Y | |
| `record_type` | Y | Y | Y | Y | |
| `keywords` | Y | Y | Y | N | |
| `crs` | Y | Y | Y | N | Format: `EPSG:XXXX` |
| `geometry_type` | Y | N | N | N | |
| `feature_count` | Y | N | N | N | |
| `band_count` | N | Y | Y | N | From raster_assets table |
| `gsd` | N | Y | Y | N | `min(abs(res_x), abs(res_y))` |
| `proj:epsg` | N | Y | Y | N | |
| `proj:shape` | N | Y | Y | N | `[height, width]` |
| `quality_detail` | Y | Y | Y | N | `.overall` score |
| `record_status` | Y | Y | Y | N | draft/ready/internal/published |
| `source_organization` | Y | Y | Y | N | |
| `updated` / `updated_by_display` | Y | Y | Y | N | Provenance |
| `dataset_count` | N | N | N | Y | Count of member datasets |
| `created` | Y | Y | Y | Y | |
| `bbox` | Y | Y | Y | N | On feature, not properties |
| `bands` | N | Y | Y | N | Array with name/data_type/nodata |

### Backend Gaps (NOT in search response)

| Field | Available In | Needed For | Effort |
|-------|-------------|------------|--------|
| `vrt_type` | `raster_assets.vrt_type` | VRT card: "Mosaic" vs "Band Stack" label | LOW - add to raster_meta query + `dataset_to_ogc_record` |
| `source_count` | `vrt_generations.source_count` | VRT card: "12 sources" | LOW - join or subquery in search |
| `resolution_strategy` | `raster_assets.resolution_strategy` | VRT card detail | LOW - same as vrt_type |
| `res_x` / `res_y` | Already queried but only exposed as `gsd` | Raster card: "10m resolution" | NONE - `gsd` already available, just display it |
| Collection modality summary | Would need aggregation query | Collection card: "3 vector, 2 raster" | MEDIUM - new aggregation |
| Collection member preview | Not available | Collection card thumbnail | HIGH - would need composite generation |

### Key Insight: raster_meta query already fetches vrt_type-adjacent data

In `search/service.py` lines 226-252, the bulk raster metadata query selects from `RasterAsset` but does NOT include `vrt_type`, `resolution_strategy`, or `status`. These columns exist on the same table. Adding them is a 3-line change.

For `source_count`, it lives on `VrtGeneration` (not `RasterAsset`), so it requires either a join or the `raster_assets` table getting a denormalized `source_count` column. However, `VrtGeneration.source_count` is per-generation, not per-dataset. The simplest path: query `VrtGeneration` for current generation source counts.

## Preview System

### How Quicklooks Work

1. **All types** use `/api/datasets/{id}/quicklook?size=256` endpoint
2. **Vector**: Server-rendered via Pillow+Shapely (`backend/app/vector/quicklook.py`)
3. **Raster**: Server-rendered via rasterio/GDAL (`backend/app/raster/quicklook.py`)
4. **VRT**: Same as raster (VRT files are readable by GDAL)
5. **Collections**: No quicklook endpoint exists

### Three-State Preview (from 260318-991)

```
Loading → quicklookSrc (image) → imgError (ImageOff icon + "Preview unavailable")
         ↘ fallback: BBoxPreview (SVG bbox map)
```

The `DatasetCard` fetches quicklook via authenticated `fetch()` call, creates a blob URL, and manages cleanup. This logic should be extracted into a shared hook or utility.

## Reusable UI Components

| Component | Location | Reusable? |
|-----------|----------|-----------|
| `Badge` | `components/ui/badge.tsx` | Yes - shadcn/ui |
| `Card` | `components/ui/card.tsx` | Yes - shadcn/ui |
| `Skeleton` | `components/ui/skeleton.tsx` | Yes - shadcn/ui |
| `Tooltip` / `TooltipContent` | `components/ui/tooltip.tsx` | Yes - shadcn/ui |
| `RecordTypeBadge` | Already shared between both cards | Yes |
| `QualityBadge` | Only used in DatasetCard | Yes - extract |
| `BBoxPreview` | In layout folder | Yes |

## Architecture Patterns

### Recommended Unified Card Structure

```
SearchResultCard (shared shell)
├── Preview area (right side, hidden mobile)
│   ├── QuicklookImage (hook-based, shared for all dataset types)
│   ├── BBoxPreview (fallback for datasets)
│   └── CollectionIcon (fallback for collections)
├── Content area (left side)
│   ├── Title (link to detail page)
│   ├── Description (line-clamp-2)
│   ├── MetadataRow (type badge + type-specific inline metadata)
│   │   ├── VectorMeta: geometry_type · feature_count · CRS · org
│   │   ├── RasterMeta: band_count · gsd · CRS · org
│   │   ├── VrtMeta: vrt_type · source_count · band_count · CRS
│   │   └── CollectionMeta: dataset_count (· modality summary future)
│   ├── Tags row (keywords, max 2 + overflow)
│   └── Provenance row (updated by · time)
```

### Extract Quicklook Fetch Logic

The quicklook fetch in DatasetCard (lines 28-62) should become a `useQuicklook(datasetId)` hook returning `{ src, isLoading, isError }`. This avoids duplicating blob URL management across card variants.

## Common Pitfalls

### Pitfall 1: Collections lack most OGCRecordProperties fields
Collection features from the search API have a minimal property set: `type`, `title`, `description`, `record_type`, `dataset_count`, `created`. They have NO `keywords`, `crs`, `quality_detail`, `record_status`, `updated_by_display`, or `geometry`. The unified card must handle these gracefully with conditional rendering, not crash on null access.

### Pitfall 2: Type assertion on collection dataset_count
SearchPage currently does `(feature.properties as Record<string, unknown>).dataset_count as number ?? 0` -- a fragile type assertion. The `OGCRecordProperties` TypeScript interface does not include `dataset_count`. This needs to be added to the type.

### Pitfall 3: Quicklook blob URL memory leaks
The current blob URL cleanup in DatasetCard uses `useEffect` cleanup + ref. If the unified card changes key/remounts frequently (e.g., during pagination), orphaned blob URLs could leak. The extracted hook must handle this carefully.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Responsive card layout | Custom flex logic per card type | Single Card shell with conditional slots |
| Quicklook fetch + blob management | Duplicate fetch logic per card | Shared `useQuicklook` hook |
| Type-specific metadata display | Big switch statement in one component | Small `VectorMeta` / `RasterMeta` / `VrtMeta` / `CollectionMeta` components |

## Backend Changes Needed

### Minimal: Add VRT fields to search response

In `backend/app/search/service.py`, the raster metadata bulk query (line 226) needs:
1. Add `RasterAsset.vrt_type` and `RasterAsset.resolution_strategy` to the select
2. Pass them through `raster_meta` dict
3. In `dataset_to_ogc_record`, add to properties when record_type is `vrt_dataset`

### Optional: VRT source_count

Query `VrtGeneration.source_count` where `vrt_dataset_id` matches and generation is current. Add to OGC record properties for VRT records.

### TypeScript type update

Add to `OGCRecordProperties` in `frontend/src/types/api.ts`:
- `dataset_count?: number` (for collections)
- `vrt_type?: string | null` (for VRT)
- `source_count?: number | null` (for VRT)
- `gsd?: number | null` (for raster/VRT)

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `frontend/src/components/search/DatasetCard.tsx`
- Direct code inspection of `frontend/src/components/search/CollectionSearchCard.tsx`
- Direct code inspection of `backend/app/search/service.py` (search endpoint + OGC record builder)
- Direct code inspection of `backend/app/raster/models.py` (RasterAsset, VrtGeneration models)
- Direct code inspection of `frontend/src/types/api.ts` (TypeScript interfaces)

## Metadata

**Confidence breakdown:**
- Current architecture: HIGH - direct code inspection
- API data availability: HIGH - traced through backend service layer
- Backend gap analysis: HIGH - verified against model definitions
- Recommended patterns: MEDIUM - architectural recommendation, not verified in production

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable codebase, patterns unlikely to change)
