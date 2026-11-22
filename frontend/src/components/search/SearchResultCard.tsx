import { memo } from 'react';
import { Link } from 'react-router';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Combine, FolderOpen, Globe, Hash, Layers, Ruler, Shapes, Table2, type LucideIcon } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { OriginBadge, datasetOrigin } from '@/components/dataset/OriginBadge';
import { FreshnessChip, HealthChip } from '@/components/dataset/SourceStateChips';
import { RecordTypeBadge } from './RecordTypeBadge';
import { formatProvenanceTime } from '@/lib/provenance-attribution';
import { formatGsd } from '@/lib/format';
import { extractBbox, geometryIcon } from '@/lib/geo-utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { ingestionStatusColors, syntheticBadgeColor } from '@/lib/status-colors';
import { useQuicklook } from '@/components/maps/hooks/use-quicklook';
import { queryKeys } from '@/lib/query-keys';
import { distinctDescription } from '@/lib/text';
import { getDataset } from '@/api/datasets';
import type { SearchResultDensity } from '@/lib/search-view';
import type { OGCRecordResponse } from '@/types/api';

const statusStyles: Record<string, string> = {
  draft: `text-xs ${ingestionStatusColors.draft}`,
  ready: `text-xs ${ingestionStatusColors.ready}`,
  internal: `text-xs ${ingestionStatusColors.internal}`,
  archived: 'text-xs',
  deprecated: 'text-xs text-muted-foreground',
};
const statusVariants: Record<string, 'outline' | 'secondary'> = {
  draft: 'outline',
  ready: 'outline',
  internal: 'outline',
  archived: 'secondary',
  deprecated: 'outline',
};

function capitalizeVrtType(vrtType: string): string {
  // 'mosaic' -> 'Mosaic', 'band_stack' -> 'Band Stack'
  return vrtType
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

interface CardSpec {
  icon: LucideIcon;
  label: string;
}

function buildCardSpecs(
  properties: OGCRecordResponse['properties'],
  t: TFunction<'search'>,
  locale: string,
): CardSpec[] {
  const recordType = properties.record_type ?? 'vector_dataset';
  const isRaster = recordType === 'raster_dataset';
  const isVrt = recordType === 'vrt_dataset';
  const specs: CardSpec[] = [];

  if (!isRaster && !isVrt && properties.geometry_type) {
    const icon = geometryIcon(properties.geometry_type) ?? Shapes;
    specs.push({ icon, label: getGeometryTypeLabel(t, properties.geometry_type) });
  }

  if (isRaster && properties.band_count != null) {
    specs.push({ icon: Layers, label: t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' }) });
  }

  if (isRaster && properties.gsd != null) {
    const label = formatGsd(properties.gsd, { isGeographic: properties.crs_is_geographic, crs: properties.crs }, locale);
    if (label) specs.push({ icon: Ruler, label });
  }

  if (isVrt && properties.vrt_type) {
    specs.push({ icon: Combine, label: capitalizeVrtType(properties.vrt_type) });
  }

  if (isVrt && properties.source_count) {
    specs.push({ icon: FolderOpen, label: t('card.sourceCount', { count: properties.source_count, defaultValue: '{{count}} sources' }) });
  }

  if (isVrt && properties.band_count != null) {
    specs.push({ icon: Layers, label: t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' }) });
  }

  if (!isRaster && !isVrt && properties.feature_count != null) {
    const isTable = recordType === 'table';
    specs.push({
      icon: Hash,
      label: isTable
        ? t('card.rowCount', { count: properties.feature_count })
        : t('card.featureCount', { count: properties.feature_count }),
    });
  }

  if (properties.crs) specs.push({ icon: Globe, label: properties.crs });

  return specs;
}

function buildAutoDescription(
  properties: OGCRecordResponse['properties'],
  t: TFunction<'search'>,
  locale: string,
): string {
  const description = distinctDescription(properties.title, properties.description);
  if (description) return description;
  const recordType = properties.record_type ?? 'vector_dataset';
  switch (recordType) {
    case 'vector_dataset':
      if (properties.geometry_type) {
        return t('card.autoDesc.vector', {
          geometryType: getGeometryTypeLabel(t, properties.geometry_type),
          count: properties.feature_count ?? 0,
          crs: properties.crs ?? '',
        });
      }
      break;
    case 'raster_dataset':
      return t('card.autoDesc.raster', {
        count: properties.band_count ?? 0,
        gsd: properties.gsd != null ? formatGsd(properties.gsd, { isGeographic: properties.crs_is_geographic, crs: properties.crs }, locale) : '',
      });
    case 'vrt_dataset':
      // A zero count means the viewer can't read any member, not that the VRT is empty.
      if (!properties.source_count) break;
      return t('card.autoDesc.vrt', {
        vrtType: properties.vrt_type ? capitalizeVrtType(properties.vrt_type) : '',
        count: properties.source_count,
      });
    case 'table':
      // An unknown row count is not an empty table.
      if (properties.feature_count == null) break;
      return t('card.autoDesc.table', { count: properties.feature_count });
    case 'tiles3d_dataset':
      return t('card.autoDesc.tiles3d');
    default:
      break;
  }
  return t('card.autoDesc.fallback');
}

interface SearchResultCardProps {
  feature: OGCRecordResponse;
  density?: SearchResultDensity;
}

export const SearchResultCard = memo(function SearchResultCard({
  feature,
  density = 'comfortable',
}: SearchResultCardProps) {
  const { t, i18n } = useTranslation('search');
  const queryClient = useQueryClient();
  const { properties } = feature;
  const recordType = properties.record_type ?? 'vector_dataset';
  const isCollection = recordType === 'collection';
  const isTable = recordType === 'table';
  const rowsKnown = properties.feature_count != null;
  const colsKnown = !!properties.column_count;
  const tableRowsText = rowsKnown ? t('card.tableRows', { count: properties.feature_count ?? 0 }) : '';
  const tableColsText = colsKnown ? t('card.tableCols', { count: properties.column_count }) : '';
  const tableThumbText =
    rowsKnown && colsKnown
      ? t('card.tableRowsColsJoined', { rows: tableRowsText, cols: tableColsText })
      : tableRowsText || tableColsText;
  const tableAriaLabel =
    rowsKnown && colsKnown
      ? t('card.tableAriaLabel', { rows: properties.feature_count, cols: properties.column_count })
      : rowsKnown
        ? t('card.tableAriaLabelNoCols', { rows: properties.feature_count })
        : colsKnown
          ? t('card.tableAriaLabelColsOnly', { cols: properties.column_count })
          : t('card.table');
  const collectionDescription = isCollection ? distinctDescription(properties.title, properties.description) : undefined;
  const origin = datasetOrigin(properties);
  const linkPath = isCollection ? `/collections/${feature.id}` : `/datasets/${feature.id}`;
  const bbox = extractBbox(feature);

  // <img src> requests carry no Authorization header, so private-dataset
  // quicklooks would 404 anonymously. useQuicklook fetches through apiFetchBlob
  // (Bearer attached) and returns a blob URL; genuine file-missing 404s are
  // cached in quicklook-cache.ts for the session.
  const featureId = feature.id as string;
  const isCompact = density === 'compact';
  const enableQuicklook = !isCompact && !isCollection && !isTable && Boolean(properties.has_quicklook);
  const { url: quicklookBlobUrl } = useQuicklook(
    enableQuicklook ? featureId : null,
    256,
    properties.quicklook_version ?? null,
  );

  const neverEditedLabel = t('card.neverEdited', { defaultValue: 'Never' });
  const noUpdateMetadataLabel = t('card.noUpdateMetadata', { defaultValue: 'No update metadata' });

  const updatedTime = formatProvenanceTime(properties.updated, {
    fallbackRelative: neverEditedLabel,
    fallbackAbsolute: neverEditedLabel,
    locale: i18n.language,
  });
  const createdTime = formatProvenanceTime(properties.created, {
    fallbackRelative: neverEditedLabel,
    fallbackAbsolute: neverEditedLabel,
    locale: i18n.language,
  });
  const updatedRelative = properties.never_edited ? neverEditedLabel : updatedTime.relative;
  const updatedAbsolute = properties.never_edited ? neverEditedLabel : updatedTime.absolute;
  const hasMissingProvenance =
    properties.never_edited &&
    !properties.updated_by_display;

  const recordStatus = properties.record_status;
  const cardSpecs = isCollection ? [] : buildCardSpecs(properties, t, i18n.language);
  const sourceOrganization =
    !isCollection && typeof properties.source_organization === 'string'
      ? properties.source_organization.trim()
      : '';
  const displayKeywords = !isCollection
    ? properties.keywords
      ?.map((keyword) => keyword.trim())
      .filter((keyword) => keyword !== '' && keyword !== 'synthetic' && keyword !== 'perf-seed') ?? []
    : [];

  const showStatusBadge = !isCollection && !!recordStatus && recordStatus !== 'published';

  const updatedLabel = hasMissingProvenance
    ? properties.created
      ? t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })
      : noUpdateMetadataLabel
    : t('card.updatedFallback', { time: updatedRelative, defaultValue: 'Updated {{time}}' });
  const updatedTitle = hasMissingProvenance ? createdTime.absolute : updatedAbsolute;
  const statusBadge =
    showStatusBadge && recordStatus ? (
      <Badge
        variant={statusVariants[recordStatus] ?? 'outline'}
        className={statusStyles[recordStatus] ?? 'text-xs'}
      >
        {t(`card.status.${recordStatus}`, {
          defaultValue: recordStatus.charAt(0).toUpperCase() + recordStatus.slice(1),
        })}
      </Badge>
    ) : null;

  // Warms the detail query on hover/focus so navigation doesn't pay chunk and
  // query serially; prefetchQuery is a no-op when the data is fresh.
  const prefetchDetail = () => {
    if (isCollection) return;
    queryClient.prefetchQuery({
      queryKey: queryKeys.datasets.detail(feature.id),
      queryFn: () => getDataset(feature.id),
      staleTime: 60_000,
    });
  };

  if (isCompact) {
    const compactSpec = isCollection
      ? properties.dataset_count != null
        ? t('collection.datasetCount', { count: properties.dataset_count, defaultValue: '{{count}} datasets' })
        : ''
      : isTable
        ? [
            properties.feature_count != null
              ? t('card.tableRows', { count: properties.feature_count })
              : '',
            properties.column_count ? t('card.tableCols', { count: properties.column_count }) : '',
          ]
            .filter(Boolean)
            .join(' · ')
        : cardSpecs
            .filter((spec) => spec.label !== properties.crs)
            .map((spec) => spec.label)
            .join(' · ');
    // Shown bare in its own column; the full sentence stays for assistive tech.
    // A collection's creation time is not an update time, so a collection
    // that reports no update time gets a dash.
    const collectionUndated = isCollection && !properties.updated;
    const updatedAbbrev = collectionUndated
      ? '—'
      : hasMissingProvenance
        ? properties.created
          ? createdTime.relative
          : '—'
        : updatedRelative;
    const updatedFull = collectionUndated ? '' : updatedLabel;
    const meta = 'truncate text-xs text-muted-foreground';
    // A dense row leaves out a healthy, fresh source and marks only one that needs attention.
    const sourceMissing = properties.source_health === 'missing' || properties.source_health === 'inaccessible';
    const sourceOverdue = properties.source_freshness === 'overdue';
    const flags =
      !isCollection && (sourceMissing || sourceOverdue || statusBadge) ? (
        <span className="flex shrink-0 items-center gap-1.5">
          {sourceMissing && <HealthChip state={properties.source_health} iconOnly />}
          {sourceOverdue && <FreshnessChip state="overdue" iconOnly />}
          {statusBadge}
        </span>
      ) : null;

    // A row of SearchResultList's grid: its columns are that list's, so every
    // row lines up. The title comes first in the source so the link is named
    // by it; `order-first` puts the type icon back in front.
    return (
      <Link
        to={linkPath}
        className="group grid gap-y-0.5 px-3 py-2 outline-none transition-colors duration-200 ease-out hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:col-span-full md:min-h-10 md:grid-cols-subgrid md:items-center md:py-1.5 pointer-coarse:md:min-h-11"
        data-testid="search-result-card"
        data-density="compact"
        onMouseEnter={prefetchDetail}
        onFocus={prefetchDetail}
      >
        <div className="flex min-w-0 items-center gap-2 md:contents">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {/* One line tall and clipped: a source that doesn't fit beside the
                title wraps out of sight instead of being cut to a fragment. */}
            <div className="flex h-5 min-w-0 flex-1 flex-wrap items-center gap-x-2 overflow-hidden">
              <h3
                className="max-w-full truncate text-sm font-semibold leading-5 text-foreground transition-colors group-hover:text-primary"
                title={properties.title}
              >
                {properties.title}
              </h3>
              {sourceOrganization && (
                <span
                  className={`hidden max-w-40 leading-5 md:block ${meta}`}
                  data-testid="dataset-card-source"
                  title={sourceOrganization}
                >
                  {sourceOrganization}
                </span>
              )}
            </div>
            {flags}
          </div>
          <RecordTypeBadge recordType={recordType} iconOnly className="order-first shrink-0 px-1.5" />
        </div>
        <div className="flex min-w-0 items-center gap-x-3 md:contents">
          <div className="flex h-4 min-w-0 flex-1 flex-wrap items-center gap-x-3 overflow-hidden md:contents">
            <span
              className={`max-w-full font-mono tracking-wide empty:hidden md:max-w-64 md:empty:block ${meta}`}
              title={compactSpec || undefined}
              data-testid="dataset-card-specs"
            >
              {compactSpec}
            </span>
            {sourceOrganization && (
              <span className={`max-w-full md:hidden ${meta}`} title={sourceOrganization}>
                {sourceOrganization}
              </span>
            )}
          </div>
          <span
            className="shrink-0 whitespace-nowrap text-xs text-muted-foreground md:text-end"
            title={collectionUndated ? undefined : updatedTitle}
            data-testid="dataset-card-updated-attribution"
          >
            <span aria-hidden="true" data-testid="dataset-card-updated-visible">{updatedAbbrev}</span>
            <span className="sr-only">{updatedFull}</span>
          </span>
        </div>
      </Link>
    );
  }

  return (
    <Link
      to={linkPath}
      className="group block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      data-testid="search-result-card"
      data-density="comfortable"
      onMouseEnter={prefetchDetail}
      onFocus={prefetchDetail}
    >
      <Card density="flush" className="cursor-pointer overflow-hidden border-border/50 bg-card/95 transition-[transform,color,background-color,box-shadow,border-color] duration-200 ease-out group-hover:-translate-y-0.5 group-hover:border-primary/20 group-hover:shadow-md">
        <div className="p-3 sm:p-4 lg:p-3.5">
          <div className="flex flex-col gap-1.5">

            {/* Band 1 — Header */}
            {isCollection ? (
              /* Collection: compact single-column layout */
              <div className="min-w-0 flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <RecordTypeBadge recordType={recordType} />
                  {properties.dataset_count != null && (
                    <Badge variant="secondary" className="text-xs">
                      {t('collection.datasetCount', { count: properties.dataset_count, defaultValue: '{{count}} datasets' })}
                    </Badge>
                  )}
                </div>
                <h3 className="block text-base font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-1">
                  {properties.title}
                </h3>
                {collectionDescription && (
                  <p className="text-sm leading-5 text-muted-foreground line-clamp-1">
                    {collectionDescription}
                  </p>
                )}
              </div>
            ) : (
              /* Dataset: grid with fixed square thumbnail */
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_132px] xl:grid-cols-[minmax(0,1fr)_148px]">
                <div className="min-w-0 flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <RecordTypeBadge recordType={recordType} />
                    {origin && <OriginBadge origin={origin} />}
                    <FreshnessChip state={properties.source_freshness} />
                    <HealthChip state={properties.source_health} />
                    {properties.keywords?.includes('synthetic') && (
                      <Badge variant="outline" className={`text-xs ${syntheticBadgeColor}`}>
                        {t('card.testData', { defaultValue: 'Test Data' })}
                      </Badge>
                    )}
                  </div>
                  <h3 className="block text-base font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-2">
                    {properties.title}
                  </h3>
                  {sourceOrganization && (
                    <p
                      className="text-xs leading-4 text-muted-foreground line-clamp-1"
                      data-testid="dataset-card-source"
                      title={sourceOrganization}
                    >
                      {sourceOrganization}
                    </p>
                  )}
                  <p
                    className="text-sm leading-5 text-muted-foreground line-clamp-2"
                    data-testid="dataset-card-description"
                  >
                    {buildAutoDescription(properties, t, i18n.language)}
                  </p>

                  {/* Specs row */}
                  {cardSpecs.length > 0 && (
                    <div className="flex flex-wrap gap-y-1" data-testid="dataset-card-specs">
                      {cardSpecs.map((item, index) => (
                        <span key={item.label} className="inline-flex items-center gap-1 text-xs font-medium font-mono tracking-wide text-muted-foreground">
                          <item.icon className="size-3 shrink-0" aria-hidden="true" />
                          {item.label}
                          {index < cardSpecs.length - 1 && (
                            <span className="mx-1.5 text-muted-foreground/40" aria-hidden="true">&middot;</span>
                          )}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Tags */}
                  {displayKeywords.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {displayKeywords.slice(0, 3).map((tag, index) => (
                        <span
                          key={`${tag}-${index}`}
                          className="inline-flex items-center rounded-md border border-border/30 bg-muted/15 px-2.5 py-0.5 text-mini text-muted-foreground"
                        >
                          {tag}
                        </span>
                      ))}
                      {displayKeywords.length > 3 && (
                        <span className="self-center text-xs text-muted-foreground">
                          {t('card.moretags', { count: displayKeywords.length - 3 })}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Updated time */}
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span data-testid="dataset-card-updated-attribution" title={updatedTitle}>
                      {updatedLabel}
                    </span>
                    {statusBadge}
                  </div>
                </div>

                {/* Right: 160x160 square preview — hidden on mobile */}
                <div className="hidden md:flex md:items-start">
                  <div className="size-[132px] shrink-0 overflow-hidden rounded-lg border border-border/40 xl:size-[148px]">
                    {isTable ? (
                      <div
                        className="flex size-[132px] flex-col items-center justify-center gap-2 bg-type-table-bg text-type-table xl:size-[148px]"
                        role="img"
                        aria-label={tableAriaLabel}
                      >
                        <Table2
                          className="h-10 w-10 opacity-80"
                          aria-hidden="true"
                          data-testid="table-thumbnail-icon"
                        />
                        <span className="text-xs font-medium font-mono tabular-nums tracking-wide">
                          {tableThumbText}
                        </span>
                      </div>
                    ) : quicklookBlobUrl ? (
                      <img
                        src={quicklookBlobUrl}
                        loading="lazy"
                        alt={t('datasetCard.quicklookAlt', { name: properties.title })}
                        className="size-[132px] object-cover dark:brightness-75 xl:size-[148px]"
                      />
                    ) : (
                      <BBoxPreview bbox={bbox} className="size-[132px] rounded-md bg-muted xl:size-[148px]" />
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Collection footer */}
            {isCollection && (
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                {properties.updated ? (
                  <span
                    data-testid="dataset-card-updated-attribution"
                    title={updatedTime.absolute}
                  >
                    {t('card.updatedFallback', { time: updatedTime.relative, defaultValue: 'Updated {{time}}' })}
                  </span>
                ) : (
                  <span />
                )}
              </div>
            )}

          </div>
        </div>
      </Card>
    </Link>
  );
});
