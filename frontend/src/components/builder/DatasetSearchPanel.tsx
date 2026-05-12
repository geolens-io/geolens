import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  Check,
  ChevronDown,
  ChevronRight,
  Database,
  Image as ImageIcon,
  Loader2,
  Plus,
  Repeat2,
  Search,
  Shuffle,
  Upload,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { searchDatasets } from '@/api/search';
import type { BasemapEntry } from '@/api/settings';
import { queryKeys } from '@/lib/query-keys';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useBasemaps } from '@/hooks/use-settings';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { getGeometryTypeLabel } from '@/i18n/labels';
import {
  basemapThumbnail,
  BLANK_BASEMAP_ID,
  normalizeBasemapConfig,
} from '@/lib/basemap-utils';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';
import type {
  MapBasemapConfig,
  MapLayerResponse,
  OGCRecordResponse,
  RecordType,
} from '@/types/api';

type DatasetSearchTab = 'all' | 'vector' | 'raster' | 'basemap';

interface DatasetSearchPanelProps {
  onAddDataset: (datasetId: string) => void;
  onDuplicateRendering: (layerId: string) => void;
  layers: MapLayerResponse[];
  isAdding: boolean;
  basemapStyle: string;
  showBasemapLabels: boolean;
  basemapConfig: MapBasemapConfig | null;
  onBasemapChange: (key: string) => void;
  onBasemapLabelsChange: (show: boolean) => void;
  onBasemapConfigChange: (value: MapBasemapConfig) => void;
}

function makeBlankBasemap(label: string): BasemapEntry {
  return {
    id: BLANK_BASEMAP_ID,
    label,
    url: BLANK_BASEMAP_ID,
    enabled: true,
    is_preset: false,
  };
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
  const quicklookUrl = !isTable && props.has_quicklook
    ? `/api/datasets/${record.id}/quicklook?size=256`
    : null;

  if (quicklookUrl) {
    return (
      <img
        src={quicklookUrl}
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

function BasemapMetadata({ entry }: { entry: BasemapEntry }) {
  const { t } = useTranslation('builder');
  return (
    <dl className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      <div className="contents">
        <dt className="text-muted-foreground">{t('search.metadata.type', { defaultValue: 'Type' })}</dt>
        <dd className="font-medium text-foreground">{t('search.basemap', { defaultValue: 'Basemap' })}</dd>
      </div>
      <div className="contents">
        <dt className="text-muted-foreground">{t('search.metadata.source', { defaultValue: 'Source' })}</dt>
        <dd className="truncate font-medium text-foreground">{entry.is_preset ? 'GeoLens' : entry.url}</dd>
      </div>
      {entry.attribution && (
        <div className="contents">
          <dt className="text-muted-foreground">{t('search.metadata.attribution', { defaultValue: 'Attribution' })}</dt>
          <dd className="truncate font-medium text-foreground">{entry.attribution}</dd>
        </div>
      )}
    </dl>
  );
}

export function DatasetSearchPanel({
  onAddDataset,
  onDuplicateRendering,
  layers,
  isAdding,
  basemapStyle,
  showBasemapLabels,
  basemapConfig,
  onBasemapChange,
  onBasemapLabelsChange,
  onBasemapConfigChange,
}: DatasetSearchPanelProps) {
  const { t } = useTranslation('builder');
  const [query, setQuery] = useState('');
  const [activeTab, setActiveTab] = useState<DatasetSearchTab>('all');
  const [sourceOrganization, setSourceOrganization] = useState('');
  const [keyword, setKeyword] = useState('');
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 300);
  const { data: basemaps } = useBasemaps();

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
    enabled: activeTab !== 'basemap',
    staleTime: 30_000,
  });

  const results = useMemo(() => {
    const features = data?.features ?? [];
    if (activeTab === 'raster') {
      return features.filter((record) => isRasterRecord(record.properties.record_type));
    }
    return features;
  }, [activeTab, data?.features]);

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

  const basemapOptions = useMemo(() => {
    const blank = makeBlankBasemap(t('basemap.blank', { defaultValue: 'No basemap' }));
    return [blank, ...(basemaps ?? []).filter((entry) => entry.enabled)];
  }, [basemaps, t]);
  const filteredBasemaps = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return basemapOptions;
    return basemapOptions.filter((entry) => entry.label.toLowerCase().includes(needle));
  }, [basemapOptions, query]);

  function handleTabChange(value: string) {
    if (!value) return;
    setActiveTab(value as DatasetSearchTab);
    setExpandedRowId(null);
  }

  function handleBasemapSwap(entry: BasemapEntry) {
    const nextConfig = normalizeBasemapConfig(basemapConfig, showBasemapLabels);
    onBasemapChange(entry.id);
    onBasemapLabelsChange(nextConfig.label_mode !== 'hidden');
    onBasemapConfigChange(nextConfig);
  }

  function renderDatasetAction(record: OGCRecordResponse, compact = false) {
    const layer = layerByDatasetId.get(record.id);
    if (layer) {
      return (
        <div className={cn('flex shrink-0 items-center gap-1', compact && 'justify-end')}>
          <Badge variant="secondary" className="h-6 rounded px-2 text-xs">
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
        aria-label={`${t('search.addToMap', { defaultValue: 'Add to map' })} ${record.properties.title}`}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        {compact && t('search.addToMap', { defaultValue: 'Add to map' })}
      </Button>
    );
  }

  function renderBasemapAction(entry: BasemapEntry, compact = false) {
    if (entry.id === basemapStyle) {
      return (
        <Button type="button" variant="secondary" size="sm" className="h-7 px-2 text-xs" disabled>
          {t('search.inUse', { defaultValue: 'in use' })}
        </Button>
      );
    }
    return (
      <Button
        type="button"
        variant={compact ? 'default' : 'outline'}
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        onClick={() => handleBasemapSwap(entry)}
      >
        <Shuffle className="h-3.5 w-3.5" aria-hidden="true" />
        {t('search.swap', { defaultValue: 'swap' })}
      </Button>
    );
  }

  return (
    <div className="min-h-0">
      <div className="space-y-2 px-1">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            placeholder={t('search.placeholder', { defaultValue: 'Search datasets' })}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-9 pl-8 text-sm"
            aria-label={t('search.placeholder', { defaultValue: 'Search datasets' })}
          />
        </div>

        <ToggleGroup
          type="single"
          value={activeTab}
          onValueChange={handleTabChange}
          className="grid w-full grid-cols-4 rounded-md bg-muted/50 p-1"
        >
          <ToggleGroupItem value="all" className="h-7 text-xs">
            {t('search.allTypes', { defaultValue: 'All' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="vector" className="h-7 text-xs">
            {t('search.vector', { defaultValue: 'Vector' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="raster" className="h-7 text-xs">
            {t('search.raster', { defaultValue: 'Raster' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="basemap" className="h-7 text-xs">
            {t('search.basemap', { defaultValue: 'Basemap' })}
          </ToggleGroupItem>
        </ToggleGroup>

        {activeTab !== 'basemap' && (sourceOptions.length > 0 || keywordOptions.length > 0 || sourceOrganization || keyword) && (
          <div className="flex flex-wrap items-center gap-1" aria-label={t('search.filters', { defaultValue: 'Filters' })}>
            {sourceOrganization && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-6 rounded px-2 text-xs"
                onClick={() => setSourceOrganization('')}
              >
                {sourceOrganization}
              </Button>
            )}
            {!sourceOrganization && sourceOptions.map((option) => (
              <Button
                key={option}
                type="button"
                variant="outline"
                size="sm"
                className="h-6 rounded px-2 text-xs"
                onClick={() => setSourceOrganization(option)}
              >
                {option}
              </Button>
            ))}
            {keyword && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-6 rounded px-2 text-xs"
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
                className="h-6 rounded px-2 text-xs text-muted-foreground"
                onClick={() => setKeyword(option)}
              >
                #{option}
              </Button>
            ))}
          </div>
        )}
      </div>

      {activeTab !== 'basemap' && isError && (
        <p className="px-2 py-2 text-sm text-destructive">
          {t('search.error', { defaultValue: 'Failed to load results' })}
        </p>
      )}

      {activeTab !== 'basemap' && (isLoading || isFetching) && (
        <div className="flex items-center justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      )}

      {activeTab !== 'basemap' && debouncedQuery.trim().length > 0 && !isLoading && results.length === 0 && (
        <p className="px-2 py-2 text-xs text-muted-foreground">{t('search.noResults')}</p>
      )}

      <div
        className={cn(
          'mt-3 max-h-[24rem] space-y-1 overflow-y-auto px-1',
          isFetching && !isLoading && activeTab !== 'basemap' && 'pointer-events-none opacity-50',
        )}
      >
        {activeTab === 'basemap' ? filteredBasemaps.map((entry) => {
          const rowId = `basemap:${entry.id}`;
          const expanded = expandedRowId === rowId;
          return (
            <div key={entry.id} className="rounded-md border border-border/60 bg-background">
              <div className="flex items-center gap-2 px-2 py-2">
                <button
                  type="button"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={expanded ? `Collapse ${entry.label}` : `Expand ${entry.label}`}
                  onClick={() => setExpandedRowId(expanded ? null : rowId)}
                >
                  {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
                <img
                  src={basemapThumbnail(entry.id)}
                  alt=""
                  aria-hidden="true"
                  className="h-9 w-9 rounded border object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{entry.label}</p>
                  <Badge variant="outline" className="mt-0.5 h-5 rounded px-1.5 text-[10px]">
                    {t('search.basemap', { defaultValue: 'Basemap' })}
                  </Badge>
                </div>
                {renderBasemapAction(entry)}
              </div>
              {expanded && (
                <div className="flex gap-3 border-t border-border/60 p-2">
                  <img
                    src={basemapThumbnail(entry.id)}
                    alt=""
                    aria-hidden="true"
                    className="h-24 w-28 rounded-md border object-cover"
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <BasemapMetadata entry={entry} />
                    <div className="flex justify-end">{renderBasemapAction(entry, true)}</div>
                  </div>
                </div>
              )}
            </div>
          );
        }) : results.map((record) => {
          const props = record.properties;
          const rowId = `dataset:${record.id}`;
          const expanded = expandedRowId === rowId;
          const recordType = props.record_type ?? 'vector_dataset';
          const meta = featureMeta(record);
          return (
            <div key={record.id} className="rounded-md border border-border/60 bg-background">
              <div className="flex items-center gap-2 px-2 py-2">
                <button
                  type="button"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={expanded ? `Collapse ${props.title}` : `Expand ${props.title}`}
                  onClick={() => setExpandedRowId(expanded ? null : rowId)}
                >
                  {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{props.title}</p>
                  <div className="mt-0.5 flex min-w-0 items-center gap-1 overflow-hidden">
                    <RecordTypeBadge recordType={recordType} className="h-5 rounded px-1.5 text-[10px]" />
                    {props.geometry_type && (
                      <Badge variant="outline" className="h-5 shrink-0 rounded px-1.5 text-[10px]">
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
        })}
      </div>

      <div className="mt-3 flex justify-end border-t border-border/60 px-1 pt-3">
        <Button asChild variant="ghost" size="sm" className="h-8 gap-1 text-xs">
          <Link to="/import">
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
            {t('search.importData', { defaultValue: 'Import data...' })}
          </Link>
        </Button>
      </div>
    </div>
  );
}
