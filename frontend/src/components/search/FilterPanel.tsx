import { lazy, Suspense, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Calendar, Loader2, MapPin, SlidersHorizontal } from 'lucide-react';
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
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
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
import { useCatalogSummary, useFacets } from '@/hooks/use-search';
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

const LazySpatialFilterPanel = lazy(async () => {
  const module = await import('./SpatialFilterPanel');
  return { default: module.SpatialFilterPanel };
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

export function FilterPanel({ totalResults }: { totalResults: number | undefined }) {
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

  // Parse OGC interval back to start/end for temporal extent inputs
  const [temporalStart, temporalEnd] = (() => {
    if (!datetime) return ['', ''];
    const parts = datetime.split('/');
    if (parts.length === 2) {
      return [parts[0] === '..' ? '' : parts[0], parts[1] === '..' ? '' : parts[1]];
    }
    return [datetime, ''];
  })();
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
  const showSecondaryFilterRow = Boolean(recordType) && (
    recordType === 'vector_dataset' || organizations.length > 0 || showSridFilter
  );
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
  const [dateOpen, setDateOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [localDateFrom, setLocalDateFrom] = useState(dateFrom);
  const [localDateTo, setLocalDateTo] = useState(dateTo);
  const spatialPanelOpen = useSearchStore((s) => s.spatialPanelOpen);
  const setSpatialPanelOpen = useSearchStore((s) => s.setSpatialPanelOpen);

  const syncLocalDates = () => {
    setLocalDateFrom(useSearchStore.getState().date_from);
    setLocalDateTo(useSearchStore.getState().date_to);
  };

  const handleApplyDate = () => {
    useSearchStore.getState().setFilter('date_from', localDateFrom);
    useSearchStore.getState().setFilter('date_to', localDateTo);
    setDateOpen(false);
  };

  const dateChipLabel = (() => {
    if (dateFrom && dateTo) return `${dateFrom} - ${dateTo}`;
    if (dateFrom) return dateFrom;
    if (dateTo) return dateTo;
    return '';
  })();

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

  const renderDesktopDateFilter = () => {
    if (dateFrom || dateTo) {
      return (
        <FilterChip
          label={dateChipLabel}
          onRemove={() => {
            useSearchStore.getState().setFilter('date_from', '');
            useSearchStore.getState().setFilter('date_to', '');
            setLocalDateFrom('');
            setLocalDateTo('');
          }}
        />
      );
    }

    return (
      <Popover
        open={dateOpen}
        onOpenChange={(open) => {
          if (open) syncLocalDates();
          setDateOpen(open);
        }}
      >
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm">
            <Calendar className="me-1 size-3.5" />
            {t('filters.dateRange')}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64">
          <div className="grid gap-2">
            <label className="text-xs font-medium text-muted-foreground">
              {t('filters.dateFrom')}
            </label>
            <Input
              type="date"
              value={localDateFrom}
              onChange={(e) => setLocalDateFrom(e.target.value)}
              className="h-8 text-sm"
            />
            <label className="text-xs font-medium text-muted-foreground">
              {t('filters.dateTo')}
            </label>
            <Input
              type="date"
              value={localDateTo}
              onChange={(e) => setLocalDateTo(e.target.value)}
              className="h-8 text-sm"
            />
            <Button
              size="sm"
              onClick={handleApplyDate}
              disabled={!localDateFrom && !localDateTo}
              className="mt-1"
            >
              {t('filters.apply')}
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  const renderDesktopLocationFilter = () => {
    if (bbox) {
      return (
        <div
          className="cursor-pointer"
          onClick={() => setSpatialPanelOpen(true)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              setSpatialPanelOpen(true);
            }
          }}
          role="button"
          tabIndex={0}
        >
          <FilterChip
            label={t('filters.areaSelected', { defaultValue: 'Area selected' })}
            onRemove={() => {
              const store = useSearchStore.getState();
              store.setFilter('bbox', '');
              store.setFilter('geometry', '');
              store.setFilter('spatial_predicate', 'intersects');
            }}
          />
        </div>
      );
    }

    return (
      <Button variant="outline" size="sm" onClick={() => setSpatialPanelOpen(true)}>
        <MapPin className="me-1 size-3.5" />
        {t('filters.location')}
      </Button>
    );
  };

  return (
    <>
      <div className="space-y-4 md:hidden">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-muted-foreground">
            {totalResults !== undefined ? (
              <span>{t('filters.datasetCount', { count: totalResults })}</span>
            ) : null}
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

      {/* Desktop: Primary filter row */}
      <div className="hidden flex-wrap items-center gap-2.5 md:flex">
        <div className="flex items-center gap-2">
          <ToggleGroup
            type="single"
            value={recordType || 'all'}
            onValueChange={(val) =>
              useSearchStore.getState().setFilter('record_type', val === 'all' ? '' : val)
            }
            className="h-8"
          >
            <ToggleGroupItem value="all" className="text-xs px-2.5 h-7">
              {t('filters.allTypes', { defaultValue: 'All' })}
              {Object.keys(counts).length > 0 && ` (${allTypeCount})`}
            </ToggleGroupItem>
            <ToggleGroupItem value="vector_dataset" className="text-xs px-2.5 h-7" disabled={counts.vector_dataset === 0}>
              {t('filters.vector', { defaultValue: 'Vector' })}
              {counts.vector_dataset !== undefined && ` (${counts.vector_dataset})`}
            </ToggleGroupItem>
            <ToggleGroupItem value="raster_dataset" className="text-xs px-2.5 h-7" disabled={counts.raster_dataset === 0}>
              {t('filters.raster', { defaultValue: 'Raster' })}
              {counts.raster_dataset !== undefined && ` (${counts.raster_dataset})`}
            </ToggleGroupItem>
            <ToggleGroupItem value="vrt_dataset" className="text-xs px-2.5 h-7" disabled={counts.vrt_dataset === 0}>
              {t('filters.vrt', { defaultValue: 'Virtual Raster' })}
              {counts.vrt_dataset !== undefined && ` (${counts.vrt_dataset})`}
            </ToggleGroupItem>
            {showsTableToggle && (
              <ToggleGroupItem value="table" className="text-xs px-2.5 h-7" disabled={counts.table === 0}>
                {t('card.table', { defaultValue: 'Table' })}
                {counts.table !== undefined && ` (${counts.table})`}
              </ToggleGroupItem>
            )}
          </ToggleGroup>
        </div>

        <KeywordFacetPicker facets={facets?.keywords} isLoading={!facets} />
        {selectedKeywords.length > 0 && selectedKeywords.length <= 2 && selectedKeywords.map((kw) => (
          <FilterChip
            key={kw}
            label={kw}
            onRemove={() => {
              const next = useSearchStore.getState().keywords.filter((k) => k !== kw);
              useSearchStore.getState().setFilter('keywords', next);
            }}
          />
        ))}
        {selectedKeywords.length > 2 && (
          <FilterChip
            label={t('filters.keywordsCount', { count: selectedKeywords.length, defaultValue: 'Keywords ({{count}})' })}
            onRemove={() => useSearchStore.getState().setFilter('keywords', [])}
          />
        )}

        {facets?.collections && facets.collections.length > 0 && (
          <div className="flex items-center gap-2">
            {collectionId ? (
              <FilterChip
                label={facets.collections.find((c) => c.id === collectionId)?.name || t('filters.collection', { defaultValue: 'Collection' })}
                onRemove={() => useSearchStore.getState().setFilter('collection_id', '')}
              />
            ) : (
              <Select
                value=""
                onValueChange={(val) => useSearchStore.getState().setFilter('collection_id', val)}
              >
                <SelectTrigger size="sm" className="data-[placeholder]:text-foreground" aria-label={t('filters.collection', { defaultValue: 'Collection' })} title={t('filters.collection', { defaultValue: 'Collection' })}>
                  <SelectValue placeholder={t('filters.collection', { defaultValue: 'Collection' })} />
                </SelectTrigger>
                <SelectContent>
                  {facets.collections.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} ({c.dataset_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">{renderDesktopLocationFilter()}</div>

        <div className="flex items-center gap-2">{renderDesktopDateFilter()}</div>

        {/* Temporal Extent filter */}
        <div className="flex items-center gap-2">
          {datetime ? (
            <FilterChip
              label={`${t('filters.temporalExtent', { defaultValue: 'Temporal Extent' })}: ${temporalStart || '..'} - ${temporalEnd || '..'}`}
              onRemove={() => useSearchStore.getState().setFilter('datetime', '')}
            />
          ) : (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm">
                  <Calendar className="me-1 size-3.5" />
                  {t('filters.temporalExtent', { defaultValue: 'Temporal Extent' })}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-64">
                <div className="grid gap-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t('filters.dateFrom')}
                  </label>
                  <Input
                    type="date"
                    defaultValue={temporalStart}
                    onChange={(e) => handleTemporalChange(e.target.value, temporalEnd)}
                    className="h-8 text-sm"
                  />
                  <label className="text-xs font-medium text-muted-foreground">
                    {t('filters.dateTo')}
                  </label>
                  <Input
                    type="date"
                    defaultValue={temporalEnd}
                    onChange={(e) => handleTemporalChange(temporalStart, e.target.value)}
                    className="h-8 text-sm"
                  />
                </div>
              </PopoverContent>
            </Popover>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label className="whitespace-nowrap text-sm font-medium text-muted-foreground">
            {t('filters.sort')}
          </label>
          <Select
            value={sortBy}
            onValueChange={(val) => useSearchStore.getState().setSortBy(val)}
          >
            <SelectTrigger
              size="sm"
              aria-label={t('filters.sort')}
              title={t('filters.sort')}
            >
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
              useSearchStore.getState().resetFilters();
              setLocalDateFrom('');
              setLocalDateTo('');
            }}
          >
            {t('filters.clearFilters')}
          </Button>
        )}

        <div className="ml-auto flex items-center gap-3 rounded-full border border-border/40 bg-muted/15 px-3 py-1 text-sm text-muted-foreground">
          {totalResults !== undefined && (
            <span>
              {bbox || geometry
                ? t('filters.spatialResultCount', { count: totalResults, defaultValue: 'Showing {{count}} in selected area' })
                : t('filters.datasetCount', { count: totalResults })}
            </span>
          )}
          {token && hasSearchState && <SaveSearchButton />}
        </div>
      </div>

      {/* Desktop: Secondary filter row (type-specific) */}
      {showSecondaryFilterRow && (
        <div
          className="hidden flex-wrap items-center gap-2.5 rounded-[18px] border border-border/40 bg-muted/15 px-3 py-1.5 md:flex"
          data-testid="secondary-filter-row"
        >
          <span className="text-xs font-medium text-muted-foreground whitespace-nowrap">
            {recordType ? getRecordTypeLabel(recordType) : ''}{' '}
            {t('filters.filtersLabel', { defaultValue: 'filters' })}
          </span>

          {recordType === 'vector_dataset' && (
            <div className="flex items-center gap-2">
              {geometryType ? (
                <FilterChip
                  label={activeGeomLabel || geometryType}
                  onRemove={() => useSearchStore.getState().setFilter('geometry_type', '')}
                />
              ) : (
                <Select
                  value=""
                  onValueChange={(val) =>
                    useSearchStore.getState().setFilter('geometry_type', val)
                  }
                >
                  <SelectTrigger
                    size="sm"
                    aria-label={t('filters.geometry')}
                    title={t('filters.geometry')}
                  >
                    <SelectValue placeholder={t('filters.geometry')} />
                  </SelectTrigger>
                  <SelectContent>
                    {GEOMETRY_TYPES.map((geometry) => (
                      <SelectItem key={geometry} value={geometry}>
                        {getGeometryTypeLabel(t, geometry)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          {organizations.length > 0 && (
            <div className="flex items-center gap-2">
              {sourceOrganization ? (
                <FilterChip
                  label={sourceOrganization}
                  onRemove={() => useSearchStore.getState().setFilter('source_organization', '')}
                />
              ) : (
                <Select
                  value=""
                  onValueChange={(val) =>
                    useSearchStore.getState().setFilter('source_organization', val)
                  }
                >
                  <SelectTrigger
                    size="sm"
                    aria-label={t('filters.organization')}
                    title={t('filters.organization')}
                  >
                    <SelectValue placeholder={t('filters.organization')} />
                  </SelectTrigger>
                  <SelectContent>
                    {organizations.map((org) => (
                      <SelectItem key={org} value={org}>{org}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          {showSridFilter && (
            <div className="flex items-center gap-2">
              {srid ? (
                <FilterChip
                  label={`EPSG:${srid}`}
                  onRemove={() => useSearchStore.getState().setFilter('srid', '')}
                />
              ) : (
                <Select
                  value=""
                  onValueChange={(val) =>
                    useSearchStore.getState().setFilter('srid', val)
                  }
                >
                  <SelectTrigger
                    size="sm"
                    aria-label={t('filters.crs')}
                    title={t('filters.crs')}
                  >
                    <SelectValue placeholder={t('filters.crs')} />
                  </SelectTrigger>
                  <SelectContent>
                    {srids.map((s) => (
                      <SelectItem key={s} value={String(s)}>{`EPSG:${s}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}
        </div>
      )}

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
                  {GEOMETRY_TYPES.map((geometry) => (
                    <SelectItem key={geometry} value={geometry}>
                      {getGeometryTypeLabel(t, geometry)}
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
                  useSearchStore.getState().resetFilters();
                  setLocalDateFrom('');
                  setLocalDateTo('');
                  setBboxOpen(false);
                }}
              >
                {t('filters.clearFilters')}
              </Button>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <Suspense fallback={null}>
        {spatialPanelOpen ? (
          <LazySpatialFilterPanel
            open={spatialPanelOpen}
            onClose={() => setSpatialPanelOpen(false)}
            onApply={(bboxValue, predicate, geometry) => {
              const store = useSearchStore.getState();
              store.setFilter('bbox', bboxValue);
              store.setFilter('spatial_predicate', predicate);
              store.setFilter('geometry', geometry ? JSON.stringify(geometry) : '');
              setSpatialPanelOpen(false);
            }}
            initialBbox={bbox}
            initialPredicate={useSearchStore.getState().spatial_predicate}
          />
        ) : null}
      </Suspense>
    </>
  );
}
