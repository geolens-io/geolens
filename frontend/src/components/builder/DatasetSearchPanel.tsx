import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  Check,
  ChevronRight,
  Database,
  GripVertical,
  Image as ImageIcon,
  Inbox,
  Plus,
  Repeat2,
  RotateCcw,
  Search,
  SearchX,
  Upload,
} from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { searchDatasets } from '@/api/search';
import { queryKeys } from '@/lib/query-keys';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';
import { useQuicklook } from '@/components/maps/hooks/use-quicklook';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Skeleton } from '@/components/ui/skeleton';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';
import type {
  MapLayerResponse,
  OGCRecordResponse,
  RecordType,
} from '@/types/api';

type DatasetSearchTab = 'all' | 'vector' | 'raster';

interface DatasetSearchPanelProps {
  onAddDataset: (datasetId: string) => void;
  onDuplicateRendering: (layerId: string) => void;
  layers: MapLayerResponse[];
  isAdding: boolean;
  initialQuery?: string;
}

function tabRecordType(tab: DatasetSearchTab): string {
  if (tab === 'vector') return 'vector_dataset';
  if (tab === 'raster') return 'raster_dataset';
  return '';
}

function isRasterRecord(recordType: RecordType | undefined) {
  return recordType === 'raster_dataset' || recordType === 'vrt_dataset';
}

function typeMeta(record: OGCRecordResponse) {
  const props = record.properties;
  const recordType = props.record_type ?? 'vector_dataset';
  if (isRasterRecord(recordType)) return 'Raster';
  if (recordType === 'table') return 'Table';
  if (props.geometry_type) return props.geometry_type;
  return 'Vector';
}

function featureMeta(record: OGCRecordResponse) {
  const props = record.properties;
  if (props.feature_count != null) return `${formatNumber(props.feature_count)} features`;
  if (props.row_count != null) return `${formatNumber(props.row_count)} rows`;
  if (props.width != null && props.height != null) {
    return `${formatNumber(props.width)} x ${formatNumber(props.height)} px`;
  }
  return null;
}

function uniqueValues(values: Array<string | null | undefined>, limit: number) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const next = value?.trim();
    if (!next || seen.has(next)) continue;
    seen.add(next);
    result.push(next);
    if (result.length >= limit) break;
  }
  return result;
}

function DatasetPreview({ record }: { record: OGCRecordResponse }) {
  const { t } = useTranslation('builder');
  const props = record.properties;
  const isTable = props.record_type === 'table';
  // useQuicklook solves the Bearer-JWT mismatch: apiFetchBlob attaches the
  // Authorization header, returning a blob URL instead of an anonymous <img src>.
  const enableQuicklook = !isTable && Boolean(props.has_quicklook);
  const { url: quicklookBlobUrl } = useQuicklook(enableQuicklook ? (record.id as string) : null, 256);

  if (quicklookBlobUrl) {
    return (
      <img
        src={quicklookBlobUrl}
        alt={t('search.previewAlt', {
          name: props.title,
          defaultValue: '{{name}} preview',
        })}
        className="h-24 w-28 rounded-md border object-cover"
        loading="lazy"
      />
    );
  }

  return (
    <div
      className="flex h-24 w-28 shrink-0 items-center justify-center rounded-md border border-border/70 bg-muted/40"
      role="img"
      aria-label={t('search.previewUnavailable', { defaultValue: 'Preview unavailable' })}
    >
      {isRasterRecord(props.record_type) ? (
        <ImageIcon className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      ) : (
        <Database className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      )}
    </div>
  );
}

function DatasetMetadata({ record }: { record: OGCRecordResponse }) {
  const { t } = useTranslation('builder');
  const props = record.properties;
  const rows = [
    [t('search.metadata.type', { defaultValue: 'Type' }), typeMeta(record)],
    [t('search.metadata.source', { defaultValue: 'Source' }), props.source_organization],
    [t('search.metadata.count', { defaultValue: 'Count' }), featureMeta(record)],
    [t('search.metadata.crs', { defaultValue: 'CRS' }), props.epsg ? `EPSG:${props.epsg}` : props.crs],
  ].filter((row): row is [string, string] => Boolean(row[1]));

  return (
    <dl className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="truncate font-medium text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// DraggableDatasetRow: wraps a dataset result row with useDraggable so users
// can drag it onto the unified stack. Registered in the lifted DndContext at
// MapBuilderPage level.
// ---------------------------------------------------------------------------
interface DraggableDatasetRowProps {
  record: OGCRecordResponse;
  expanded: boolean;
  setExpandedRowId: (id: string | null) => void;
  renderDatasetAction: (record: OGCRecordResponse, compact?: boolean) => ReactNode;
}

const DraggableDatasetRow = memo(function DraggableDatasetRow({
  record,
  expanded,
  setExpandedRowId,
  renderDatasetAction,
}: DraggableDatasetRowProps) {
  const { t } = useTranslation('builder');
  const props = record.properties;
  const rowId = `dataset:${record.id}`;
  const recordType = props.record_type ?? 'vector_dataset';
  const meta = featureMeta(record);

  const { attributes, listeners, setActivatorNodeRef, setNodeRef, isDragging } = useDraggable({
    id: `catalog:${record.id}`,
    data: {
      source: 'catalog' as const,
      datasetId: record.id,
      recordType,
      name: props.title ?? 'Dataset',
    },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        'group/row rounded-md border border-border/60 bg-background',
        isDragging && 'opacity-40 bg-[var(--surface-2)]',
      )}
    >
      <div className={cn('flex items-center gap-2 px-2 py-2', !isDragging && 'cursor-grab', isDragging && 'cursor-grabbing')}>
        {/* Grip handle — hidden at rest, appears on row hover */}
        <button
          ref={setActivatorNodeRef}
          type="button"
          {...attributes}
          {...listeners}
          // fix(#430 V-11): reworded so it no longer substring-matches "Add to map"
          // (the row/details action labels), keeping accessible names distinct.
          aria-label={t('search.dragHandle', { defaultValue: 'Drag into map' })}
          // Phase 1199 STACK-05: reveal the catalog drag grip on coarse-pointer/touch.
          data-touch-reveal=""
          className="flex h-7 w-5 shrink-0 items-center justify-center cursor-grab opacity-0 group-hover/row:opacity-35 hover:opacity-70 focus-visible:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm active:cursor-grabbing"
          // builder-audit #338 P1-10: {...listeners} spreads dnd-kit's PointerSensor
          // activator (incl. onPointerDown). A bare onPointerDown={stopPropagation}
          // AFTER the spread would OVERRIDE the activator and break drag-to-add from
          // the handle. Compose instead: invoke the activator first, then stop
          // propagation so the row-level pointer handlers stay suppressed.
          onPointerDown={(e) => {
            listeners?.onPointerDown?.(e);
            e.stopPropagation();
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={expanded
            ? t('search.collapseResult', { name: props.title, defaultValue: 'Collapse {{name}}' })
            : t('search.expandResult', { name: props.title, defaultValue: 'Expand {{name}}' })}
          onClick={() => setExpandedRowId(expanded ? null : rowId)}
        >
          <ChevronRight className={cn(
            'h-3.5 w-3.5 transition-transform duration-[--motion-fast]',
            expanded ? 'rotate-90' : 'rtl-mirror',
          )} />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{props.title}</p>
          <div className="mt-0.5 flex min-w-0 items-center gap-1 overflow-hidden">
            <RecordTypeBadge recordType={recordType} className="h-5 rounded-sm px-1.5 text-2xs" />
            {props.geometry_type && (
              <Badge variant="outline" className="h-5 shrink-0 rounded-sm px-1.5 text-2xs">
                {getGeometryTypeLabel(t, props.geometry_type)}
              </Badge>
            )}
            {meta && <span className="truncate text-xs text-muted-foreground">{meta}</span>}
          </div>
        </div>
        {renderDatasetAction(record)}
      </div>
      {expanded && (
        <div className="flex gap-3 border-t border-border/60 p-2">
          <DatasetPreview record={record} />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <DatasetMetadata record={record} />
            {props.description && (
              <p className="line-clamp-2 text-xs leading-snug text-muted-foreground">{props.description}</p>
            )}
            <div className="flex justify-end">{renderDatasetAction(record, true)}</div>
          </div>
        </div>
      )}
    </div>
  );
});

export function DatasetSearchPanel({
  onAddDataset,
  onDuplicateRendering,
  layers,
  isAdding,
  initialQuery,
}: DatasetSearchPanelProps) {
  const { t } = useTranslation('builder');
  const queryClient = useQueryClient();
  // builder-audit #338 SEARCH-01: gate the Import/Upload CTAs on capability (matching
  // the catalog SearchPage, fix GLUX-006) so a viewer-capable session that lands
  // here does not see dead-end Import affordances. Keep the `!!token` guard too:
  // on logout the cached permissions query can briefly still return data, while
  // `token` clears synchronously in the auth store.
  const token = useAuthStore((s) => s.token);
  const { can } = usePermissions();
  const canImport = !!token && can('upload');
  const [query, setQuery] = useState<string>(initialQuery ?? '');
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-select pre-filled value on mount so the user can immediately replace it.
  // useEffect runs once because initialQuery is captured at mount time; if the modal
  // is reopened with a new initialQuery, the parent unmounts/remounts the dialog content
  // (Radix Dialog default behavior), so this effect re-fires per modal-open.
  useEffect(() => {
    if (initialQuery && inputRef.current) {
      inputRef.current.select();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount per modal open
  }, []);

  const [activeTab, setActiveTab] = useState<DatasetSearchTab>('all');
  const [sourceOrganization, setSourceOrganization] = useState('');
  const [keyword, setKeyword] = useState('');
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 300);

  const recordType = tabRecordType(activeTab);
  const searchParams: Record<string, string> = { limit: '20' };
  if (debouncedQuery.trim()) searchParams.q = debouncedQuery.trim();
  if (recordType) searchParams.record_type = recordType;
  if (sourceOrganization) searchParams.source_organization = sourceOrganization;
  if (keyword) searchParams.keywords = keyword;

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: [
      ...queryKeys.datasetSearch.results(debouncedQuery, recordType),
      sourceOrganization,
      keyword,
    ],
    queryFn: () => searchDatasets(searchParams),
    staleTime: 30_000,
  });

  // Per UI-SPEC §4a: the `record_type` query param at line ~215 already constrains
  // the backend query. The previous client-side isRasterRecord filter was a bug that
  // capped raster discovery to whatever appeared in the all-types page-20 result.
  // isRasterRecord() is still used by typeMeta() for display purposes.
  const results = useMemo(() => data?.features ?? [], [data?.features]);

  const sourceOptions = useMemo(
    () => uniqueValues((data?.features ?? []).map((record) => record.properties.source_organization), 4),
    [data?.features],
  );
  const keywordOptions = useMemo(
    () => uniqueValues((data?.features ?? []).flatMap((record) => record.properties.keywords ?? []), 6),
    [data?.features],
  );
  const layerByDatasetId = useMemo(() => {
    const map = new Map<string, MapLayerResponse>();
    for (const layer of layers) {
      if (layer.dataset_id && !map.has(layer.dataset_id)) map.set(layer.dataset_id, layer);
    }
    return map;
  }, [layers]);

  function handleTabChange(value: string) {
    if (!value) return;
    setActiveTab(value as DatasetSearchTab);
    setExpandedRowId(null);
  }

  function renderDatasetAction(record: OGCRecordResponse, compact = false) {
    const layer = layerByDatasetId.get(record.id);
    if (layer) {
      return (
        <div className={cn('flex shrink-0 items-center gap-1', compact && 'justify-end')}>
          <Badge variant="secondary" className="h-6 rounded-sm px-2 text-xs">
            <Check className="me-1 h-3 w-3" aria-hidden="true" />
            {t('search.added', { defaultValue: 'Added' })}
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={() => onDuplicateRendering(layer.id)}
            disabled={isAdding}
          >
            <Repeat2 className="h-3.5 w-3.5" aria-hidden="true" />
            {t('search.anotherRendering', { defaultValue: 'another rendering' })}
          </Button>
        </div>
      );
    }

    return (
      <Button
        type="button"
        variant={compact ? 'default' : 'ghost'}
        size={compact ? 'sm' : 'icon'}
        className={compact ? 'h-8 gap-1 px-3 text-xs' : 'h-7 w-7 shrink-0'}
        onClick={() => onAddDataset(record.id)}
        disabled={isAdding}
        title={t('search.addToMap', { defaultValue: 'Add to map' })}
        // fix(#430 V-11): the row action and the expanded-details action both render
        // this button; give the details-panel instance a distinct accessible
        // name so screen readers/role+name queries don't see two identical
        // "Add to map <name>" buttons in one result row.
        aria-label={
          compact
            ? `${t('search.addToMapDetails', { defaultValue: 'Add to map (details panel)' })} ${record.properties.title}`
            : `${t('search.addToMap', { defaultValue: 'Add to map' })} ${record.properties.title}`
        }
      >
        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        {compact && t('search.addToMap', { defaultValue: 'Add to map' })}
      </Button>
    );
  }

  return (
    <div className="min-h-0 min-w-0 overflow-hidden">
      <div className="min-w-0 space-y-2 px-1">
        <div className="relative min-w-0">
          <Search className="pointer-events-none absolute start-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            ref={inputRef}
            placeholder={t('search.placeholder', { defaultValue: 'Search datasets' })}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-9 ps-8 text-sm"
            aria-label={t('search.placeholder', { defaultValue: 'Search datasets' })}
          />
        </div>

        <ToggleGroup
          type="single"
          value={activeTab}
          onValueChange={handleTabChange}
          className="grid w-full min-w-0 grid-cols-3 rounded-md bg-muted/50 p-1"
        >
          <ToggleGroupItem value="all" className="h-7 min-w-0 px-2 text-xs">
            {t('search.allTypes', { defaultValue: 'All' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="vector" className="h-7 min-w-0 px-2 text-xs">
            {t('search.vector', { defaultValue: 'Vector' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="raster" className="h-7 min-w-0 px-2 text-xs">
            {t('search.raster', { defaultValue: 'Raster' })}
          </ToggleGroupItem>
        </ToggleGroup>

        {(sourceOptions.length > 0 || keywordOptions.length > 0 || sourceOrganization || keyword) && (
          <div className="flex min-w-0 flex-wrap items-center gap-1" aria-label={t('search.filters', { defaultValue: 'Filters' })}>
            {sourceOrganization && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-7 min-w-0 max-w-full rounded-sm px-2 text-xs"
                onClick={() => setSourceOrganization('')}
              >
                <span className="block truncate">{sourceOrganization}</span>
              </Button>
            )}
            {!sourceOrganization && sourceOptions.map((option) => (
              <Button
                key={option}
                type="button"
                variant="outline"
                size="sm"
                className="h-7 min-w-0 max-w-full rounded-sm px-2 text-xs"
                onClick={() => setSourceOrganization(option)}
              >
                <span className="block truncate">{option}</span>
              </Button>
            ))}
            {keyword && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-7 rounded-sm px-2 text-xs"
                onClick={() => setKeyword('')}
              >
                #{keyword}
              </Button>
            )}
            {!keyword && keywordOptions.slice(0, 4).map((option) => (
              <Button
                key={option}
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 rounded-sm px-2 text-xs text-muted-foreground"
                onClick={() => setKeyword(option)}
              >
                #{option}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* State: Error */}
      {isError && (
        <div role="alert" className="flex flex-col items-center gap-2 px-4 py-6 text-center">
          <AlertCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
          <p className="text-sm text-foreground text-center">
            {t('search.error', { defaultValue: 'Failed to load datasets. Check your connection and try again.' })}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => queryClient.invalidateQueries({ queryKey: queryKeys.datasetSearch.results(debouncedQuery, recordType) })}
          >
            <RotateCcw className="me-1 h-3.5 w-3.5" aria-hidden="true" />
            {t('search.retry', { defaultValue: 'Try again' })}
          </Button>
        </div>
      )}

      {/* State: Loading — first fetch skeleton rows (AUD-10) */}
      {!isError && isLoading && (
        <div className="mt-3 space-y-1 px-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[58px] w-full rounded-md" />
          ))}
        </div>
      )}
      {/* State: Refetching — progress band over stale list (AUD-13) */}
      {!isError && isFetching && !isLoading && (
        <div className="h-0.5 w-full bg-[var(--primary)] animate-pulse" />
      )}

      {/* State A: Unfiltered empty — catalog is empty */}
      {!isLoading && !isFetching && !isError
        && debouncedQuery.trim().length === 0 && results.length === 0 && (
        <div role="status" className="flex flex-col items-center gap-2 px-4 py-6">
          <Inbox className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="text-center text-sm font-semibold">
            {t('search.catalogEmpty', { defaultValue: 'Your catalog is empty. Upload a dataset to get started.' })}
          </p>
          {/* builder-audit #338 SEARCH-01: only show the Upload CTA when the session can upload. */}
          {canImport && (
            <Button variant="ghost" size="sm" asChild>
              <Link to="/import">
                {t('search.uploadCta', { defaultValue: 'Upload a file →' })}
              </Link>
            </Button>
          )}
          <Button variant="link" size="sm" className="text-muted-foreground text-xs" asChild>
            <Link to="/collections">
              {t('search.browseCatalogCta', { defaultValue: 'Browse public catalog →' })}
            </Link>
          </Button>
        </div>
      )}

      {/* State B: Zero-result — query entered, no matches */}
      {!isLoading && !isFetching && !isError
        && debouncedQuery.trim().length > 0 && results.length === 0 && (
        <div role="status" className="flex flex-col items-center gap-2 px-4 py-6">
          <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="text-center text-sm font-semibold">
            {t('search.zeroResultHeading', { defaultValue: "No datasets match '{{query}}'", query: debouncedQuery.trim() })}
          </p>
          <p className="text-center text-xs text-muted-foreground">
            {t('search.zeroResultBody', { defaultValue: 'Try a different search term, or browse all datasets.' })}
          </p>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('search.clearSearch', { defaultValue: 'Clear search and show all datasets' })}
            onClick={() => setQuery('')}
          >
            {t('search.clearSearch', { defaultValue: 'Clear search' })}
          </Button>
        </div>
      )}

      <div
        className={cn(
          'mt-3 max-h-[24rem] space-y-1 overflow-y-auto px-1',
          isFetching && !isLoading && 'pointer-events-none opacity-50',
        )}
      >
        {results.map((record) => (
          <DraggableDatasetRow
            key={record.id}
            record={record}
            expanded={expandedRowId === `dataset:${record.id}`}
            setExpandedRowId={setExpandedRowId}
            renderDatasetAction={renderDatasetAction}
          />
        ))}
      </div>

      {/* builder-audit #338 SEARCH-01: gate the footer Import CTA on can('upload'),
          matching the catalog search panel. */}
      {canImport && (
        <div className="mt-3 flex justify-end border-t border-border/60 px-1 pt-3">
          <Button asChild variant="ghost" size="sm" className="h-8 gap-1 text-xs">
            <Link to="/import">
              <Upload className="h-3.5 w-3.5" aria-hidden="true" />
              {t('search.importData', { defaultValue: 'Import data...' })}
            </Link>
          </Button>
        </div>
      )}
    </div>
  );
}
