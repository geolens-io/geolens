import { lazy, Suspense, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, MapPin, SlidersHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { FilterChip } from './FilterChip';
import { KeywordFacetPicker } from './KeywordFacetPicker';
import { SaveSearchButton } from './SavedSearches';
import { useSearchStore } from '@/stores/search-store';
import { useAuthStore } from '@/stores/auth-store';
import { useCatalogSummary, useFacets } from '@/components/search/hooks/use-search';
import { getGeometryTypeLabel, getSearchSortLabel } from '@/i18n/labels';

const GEOMETRY_TYPES = [
  'POINT',
  'LINESTRING',
  'POLYGON',
  'MULTIPOINT',
  'MULTILINESTRING',
  'MULTIPOLYGON',
] as const;
const SORT_OPTIONS = ['relevance', 'date_added', 'name', 'last_updated'] as const;
const ANY_GEOMETRY_VALUE = '__all__';

const LazyBboxMapPicker = lazy(async () => {
  const module = await import('./BboxMapPicker');
  return { default: module.BboxMapPicker };
});

function MapPickerFallback() {
  const { t } = useTranslation('search');

  return (
    <div className="flex h-40 items-center justify-center rounded-xl border bg-muted/20 text-sm text-muted-foreground">
      <Loader2 className="me-2 size-4 animate-spin" />
      {t('bbox.loading', { defaultValue: 'Loading map...' })}
    </div>
  );
}

/**
 * Parse an OGC datetime interval string into [start, end] for display.
 */
function parseTemporalInterval(datetime: string): [string, string] {
  if (!datetime) return ['', ''];
  const parts = datetime.split('/');
  if (parts.length === 2) {
    return [
      parts[0] === '..' ? '' : parts[0],
      parts[1] === '..' ? '' : parts[1],
    ];
  }
  return [datetime, ''];
}

interface FilterSheetProps {
  totalResults: number | undefined;
}

/**
 * Mobile filter sheet -- condensed bar with chip row plus full-screen bottom
 * sheet replicating all catalog filter controls for small viewports.
 *
 * Extracted from FilterPanel to keep the desktop toolbar and mobile sheet
 * independently maintainable.
 *
 * State source: All filter state is read from `useSearchStore` (zustand).
 */
export function FilterSheet({ totalResults }: FilterSheetProps) {
  const { t } = useTranslation('search');
  const geometryType = useSearchStore((s) => s.geometry_type);
  const bbox = useSearchStore((s) => s.bbox);
  const dateFrom = useSearchStore((s) => s.date_from);
  const dateTo = useSearchStore((s) => s.date_to);
  const sortBy = useSearchStore((s) => s.sort_by);
  const recordType = useSearchStore((s) => s.record_type);
  const collectionId = useSearchStore((s) => s.collection_id);
  const sourceOrganization = useSearchStore((s) => s.source_organization);
  const srid = useSearchStore((s) => s.srid);
  const datetime = useSearchStore((s) => s.datetime);
  const selectedKeywords = useSearchStore((s) => s.keywords);
  const geometry = useSearchStore((s) => s.geometry);
  const q = useSearchStore((s) => s.q);
  const token = useAuthStore((s) => s.token);

  const { data: facets } = useFacets();
  const counts = facets?.record_type ?? {};
  const allTypeCount =
    (counts.vector_dataset ?? 0) +
    (counts.raster_dataset ?? 0) +
    (counts.vrt_dataset ?? 0) +
    (counts.table ?? 0);

  const { data: summaries } = useCatalogSummary();

  const [temporalStart, temporalEnd] = parseTemporalInterval(datetime);
  const organizations = summaries?.source_organization ?? [];
  const srids = summaries?.srid ?? [];

  const handleTemporalChange = (start: string, end: string) => {
    let interval = '';
    if (start && end) interval = `${start}/${end}`;
    else if (start) interval = `${start}/..`;
    else if (end) interval = `../${end}`;
    useSearchStore.getState().setFilter('datetime', interval);
  };

  const hasActiveFilters =
    geometryType !== '' || bbox !== '' || dateFrom !== '' || dateTo !== '' || recordType !== '' || collectionId !== '' || sourceOrganization !== '' || srid !== '' || datetime !== '' || selectedKeywords.length > 0;
  const hasToolbarChanges = hasActiveFilters || sortBy !== 'relevance';
  const hasSearchState = hasToolbarChanges || q !== '';
  const activeFilterCount = [geometryType, bbox, dateFrom || dateTo, recordType, collectionId, sourceOrganization, srid, datetime, selectedKeywords.length > 0 ? 'kw' : ''].filter(Boolean).length;
  const activeGeomLabel = geometryType ? getGeometryTypeLabel(t, geometryType) : null;
  const showsTableToggle = counts.table !== undefined;
  const showGeometryFilter = recordType !== 'raster_dataset' && recordType !== 'vrt_dataset' && recordType !== 'table';
  const showSridFilter = srids.length > 0 && recordType !== 'table';
  const getRecordTypeLabel = (value: string) => {
    switch (value) {
      case 'vector_dataset':
        return t('filters.vector', { defaultValue: 'Vector' });
      case 'raster_dataset':
        return t('filters.raster', { defaultValue: 'Raster' });
      case 'vrt_dataset':
        return t('filters.vrt', { defaultValue: 'Virtual Raster' });
      case 'table':
        return t('card.table', { defaultValue: 'Table' });
      default:
        return value;
    }
  };

  const [bboxOpen, setBboxOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [localDateFrom, setLocalDateFrom] = useState(dateFrom);
  const [localDateTo, setLocalDateTo] = useState(dateTo);

  const syncLocalDates = () => {
    setLocalDateFrom(useSearchStore.getState().date_from);
    setLocalDateTo(useSearchStore.getState().date_to);
  };

  const handleApplyDate = () => {
    useSearchStore.getState().setFilter('date_from', localDateFrom);
    useSearchStore.getState().setFilter('date_to', localDateTo);
  };

  const dateChipLabel = (() => {
    if (dateFrom && dateTo) return `${dateFrom} - ${dateTo}`;
    if (dateFrom) return dateFrom;
    if (dateTo) return dateTo;
    return '';
  })();

  const clearFilters = () => {
    useSearchStore.getState().resetFilters();
    setLocalDateFrom('');
    setLocalDateTo('');
  };

  const totalResultsLabel =
    totalResults !== undefined
      ? bbox || geometry
        ? t('filters.spatialResultCount', { count: totalResults, defaultValue: 'Showing {{count}} in selected area' })
        : t('filters.datasetCount', { count: totalResults })
      : null;

  const renderMapPicker = () => (
    <Suspense fallback={<MapPickerFallback />}>
      <LazyBboxMapPicker
        onBboxSelected={(bboxValue) => {
          useSearchStore.getState().setFilter('bbox', bboxValue);
          setBboxOpen(false);
        }}
      />
    </Suspense>
  );

  return (
    <>
      {/* ---- Mobile bar + chip row ---- */}
      <div className="space-y-4 md:hidden">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-muted-foreground">
            {totalResultsLabel ? <span>{totalResultsLabel}</span> : null}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant={activeFilterCount > 0 ? 'default' : 'outline'}
              size="sm"
              className="rounded-full border-border/60 shadow-sm"
              onClick={() => {
                syncLocalDates();
                setMobileFiltersOpen(true);
              }}
            >
              <SlidersHorizontal className="size-4" />
              {t('filters.filtersButton', { defaultValue: 'Filters' })}
              {activeFilterCount > 0 && (
                <span className="rounded-full bg-background/20 px-1.5 py-0 text-[11px] font-semibold">
                  {activeFilterCount}
                </span>
              )}
            </Button>
            {token && hasSearchState && <SaveSearchButton />}
          </div>
        </div>

        {hasActiveFilters && (
          <div className="flex flex-wrap items-center gap-2">
            {recordType && (
              <FilterChip
                label={getRecordTypeLabel(recordType)}
                onRemove={() => useSearchStore.getState().setFilter('record_type', '')}
              />
            )}
            {collectionId && facets?.collections && (
              <FilterChip
                label={facets.collections.find((c) => c.id === collectionId)?.name || t('filters.collection', { defaultValue: 'Collection' })}
                onRemove={() => useSearchStore.getState().setFilter('collection_id', '')}
              />
            )}
            {geometryType && (
              <FilterChip
                label={activeGeomLabel || geometryType}
                onRemove={() => useSearchStore.getState().setFilter('geometry_type', '')}
              />
            )}
            {sourceOrganization && (
              <FilterChip
                label={sourceOrganization}
                onRemove={() => useSearchStore.getState().setFilter('source_organization', '')}
              />
            )}
            {srid && (
              <FilterChip
                label={`EPSG:${srid}`}
                onRemove={() => useSearchStore.getState().setFilter('srid', '')}
              />
            )}
            {bbox && (
              <FilterChip
                label={t('filters.areaSelected', { defaultValue: 'Area selected' })}
                onRemove={() => {
                  const store = useSearchStore.getState();
                  store.setFilter('bbox', '');
                  store.setFilter('geometry', '');
                  store.setFilter('spatial_predicate', 'intersects');
                }}
              />
            )}
            {(dateFrom || dateTo) && (
              <FilterChip
                label={dateChipLabel}
                onRemove={() => {
                  useSearchStore.getState().setFilter('date_from', '');
                  useSearchStore.getState().setFilter('date_to', '');
                  setLocalDateFrom('');
                  setLocalDateTo('');
                }}
              />
            )}
            {datetime && (
              <FilterChip
                label={`${t('filters.temporalExtent', { defaultValue: 'Temporal Extent' })}: ${temporalStart || '..'} - ${temporalEnd || '..'}`}
                onRemove={() => useSearchStore.getState().setFilter('datetime', '')}
              />
            )}
            {selectedKeywords.length > 0 && selectedKeywords.map((kw) => (
              <FilterChip
                key={kw}
                label={kw}
                onRemove={() => {
                  const next = selectedKeywords.filter((k) => k !== kw);
                  useSearchStore.getState().setFilter('keywords', next);
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* ---- Mobile filter sheet (full-screen overlay) ---- */}
      <Sheet
        open={mobileFiltersOpen}
        onOpenChange={(open) => {
          if (open) syncLocalDates();
          if (!open) setBboxOpen(false);
          setMobileFiltersOpen(open);
        }}
      >
        <SheetContent
          side="bottom"
          className="max-h-[85vh] rounded-t-3xl border-x-0 border-b-0 px-0"
        >
          <SheetHeader className="px-4 pb-2">
            <SheetTitle>
              {t('filters.filtersButton', { defaultValue: 'Filters' })}
            </SheetTitle>
            <SheetDescription>
              {t('filters.sheetDescription', {
                defaultValue: 'Refine results without leaving the search page.',
              })}
            </SheetDescription>
          </SheetHeader>

          <div className="space-y-5 overflow-y-auto px-4 pb-6">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.type', { defaultValue: 'Type' })}
            </label>
            <ToggleGroup
              type="single"
              value={recordType || 'all'}
              onValueChange={(val) =>
                useSearchStore.getState().setFilter('record_type', val === 'all' ? '' : val)
              }
              className="w-full"
            >
              <ToggleGroupItem value="all" className="flex-1 text-xs">
                {t('filters.allTypes', { defaultValue: 'All' })}
                {Object.keys(counts).length > 0 && ` (${allTypeCount})`}
              </ToggleGroupItem>
              <ToggleGroupItem value="vector_dataset" className="flex-1 text-xs" disabled={counts.vector_dataset === 0}>
                {t('filters.vector', { defaultValue: 'Vector' })}
                {counts.vector_dataset !== undefined && ` (${counts.vector_dataset})`}
              </ToggleGroupItem>
              <ToggleGroupItem value="raster_dataset" className="flex-1 text-xs" disabled={counts.raster_dataset === 0}>
                {t('filters.raster', { defaultValue: 'Raster' })}
                {counts.raster_dataset !== undefined && ` (${counts.raster_dataset})`}
              </ToggleGroupItem>
              <ToggleGroupItem value="vrt_dataset" className="flex-1 text-xs" disabled={counts.vrt_dataset === 0}>
                {t('filters.vrt', { defaultValue: 'VRT' })}
                {counts.vrt_dataset !== undefined && ` (${counts.vrt_dataset})`}
              </ToggleGroupItem>
              {showsTableToggle && (
                <ToggleGroupItem value="table" className="flex-1 text-xs" disabled={counts.table === 0}>
                  {t('card.table', { defaultValue: 'Table' })}
                  {counts.table !== undefined && ` (${counts.table})`}
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          </div>

          {showGeometryFilter && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.geometry')}
            </label>
            <Select
              value={geometryType || ANY_GEOMETRY_VALUE}
              onValueChange={(val) =>
                useSearchStore
                  .getState()
                  .setFilter('geometry_type', val === ANY_GEOMETRY_VALUE ? '' : val)
              }
            >
              <SelectTrigger className="w-full" aria-label={t('filters.geometry')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY_GEOMETRY_VALUE}>
                  {t('filters.anyGeometry', { defaultValue: 'Any geometry' })}
                </SelectItem>
                {GEOMETRY_TYPES.map((geom) => (
                  <SelectItem key={geom} value={geom}>
                    {getGeometryTypeLabel(t, geom)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.keywords', { defaultValue: 'Keywords' })}
            </label>
            <KeywordFacetPicker facets={facets?.keywords} isLoading={!facets} />
          </div>

          {facets?.collections && facets.collections.length > 0 && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                {t('filters.collection', { defaultValue: 'Collection' })}
              </label>
              <Select
                value={collectionId || '__all__'}
                onValueChange={(val) =>
                  useSearchStore.getState().setFilter('collection_id', val === '__all__' ? '' : val)
                }
              >
                <SelectTrigger className="w-full" aria-label={t('filters.collection', { defaultValue: 'Collection' })}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">{t('filters.anyCollection', { defaultValue: 'Any collection' })}</SelectItem>
                  {facets.collections.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} ({c.dataset_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {organizations.length > 0 && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                {t('filters.organization')}
              </label>
              <Select
                value={sourceOrganization || '__all__'}
                onValueChange={(val) =>
                  useSearchStore.getState().setFilter('source_organization', val === '__all__' ? '' : val)
                }
              >
                <SelectTrigger className="w-full" aria-label={t('filters.organization')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">{t('filters.anyOrganization')}</SelectItem>
                  {organizations.map((org) => (
                    <SelectItem key={org} value={org}>{org}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {showSridFilter && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                {t('filters.crs')}
              </label>
              <Select
                value={srid || '__all__'}
                onValueChange={(val) =>
                  useSearchStore.getState().setFilter('srid', val === '__all__' ? '' : val)
                }
              >
                <SelectTrigger className="w-full" aria-label={t('filters.crs')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">{t('filters.anyCrs')}</SelectItem>
                  {srids.map((s) => (
                    <SelectItem key={s} value={String(s)}>{`EPSG:${s}`}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-sm font-medium text-foreground">
                {t('filters.location')}
              </label>
              {bbox && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const store = useSearchStore.getState();
                    store.setFilter('bbox', '');
                    store.setFilter('geometry', '');
                    store.setFilter('spatial_predicate', 'intersects');
                  }}
                >
                  {t('filters.clearLocation', { defaultValue: 'Clear location' })}
                </Button>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start"
              onClick={() => setBboxOpen((open) => !open)}
            >
              <MapPin className="size-4" />
              {bbox
                ? t('filters.updateLocation', {
                    defaultValue: 'Update location area',
                  })
                : t('filters.location')}
            </Button>
            {bbox && (
              <p className="text-xs text-muted-foreground">
                {t('filters.locationApplied', {
                  defaultValue: 'A map area is currently limiting the results.',
                })}
              </p>
            )}
            {bboxOpen ? renderMapPicker() : null}
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.dateRange')}
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {t('filters.dateFrom')}
                </label>
                <Input
                  type="date"
                  value={localDateFrom}
                  onChange={(e) => setLocalDateFrom(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {t('filters.dateTo')}
                </label>
                <Input
                  type="date"
                  value={localDateTo}
                  onChange={(e) => setLocalDateTo(e.target.value)}
                />
              </div>
            </div>
            <Button
              size="sm"
              onClick={handleApplyDate}
              disabled={!localDateFrom && !localDateTo}
            >
              {t('filters.apply')}
            </Button>
          </div>

          {/* Temporal Extent (mobile) */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.temporalExtent', { defaultValue: 'Temporal Extent' })}
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {t('filters.dateFrom')}
                </label>
                <Input
                  type="date"
                  value={temporalStart}
                  onChange={(e) => handleTemporalChange(e.target.value, temporalEnd)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {t('filters.dateTo')}
                </label>
                <Input
                  type="date"
                  value={temporalEnd}
                  onChange={(e) => handleTemporalChange(temporalStart, e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              {t('filters.sort')}
            </label>
            <Select
              value={sortBy}
              onValueChange={(val) => useSearchStore.getState().setSortBy(val)}
            >
              <SelectTrigger className="w-full" aria-label={t('filters.sort')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>
                    {getSearchSortLabel(t, option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {hasToolbarChanges && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                clearFilters();
                setBboxOpen(false);
              }}
            >
              {t('filters.clearFilters')}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
    </>
  );
}
