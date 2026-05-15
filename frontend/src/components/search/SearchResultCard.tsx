import { memo } from 'react';
import { Link } from 'react-router';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Combine, FolderOpen, Globe, Hash, Layers, Ruler, Shapes, Table2, type LucideIcon } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { RecordTypeBadge } from './RecordTypeBadge';
import { formatProvenanceTime } from '@/lib/provenance-attribution';
import { extractBbox, geometryIcon } from '@/lib/geo-utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { ingestionStatusColors, syntheticBadgeColor } from '@/lib/status-colors';
import { isQuicklookKnownMissing, markQuicklookMissing } from '@/lib/quicklook-cache';
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

function formatGsd(gsd: number, crs: string | null | undefined, locale: string): string {
  // For geographic CRS (degree-based), don't show GSD — it's meaningless as a distance
  if (crs && /^EPSG:4326$/i.test(crs)) return '';
  // Sub-meter
  if (gsd < 1) return `${(gsd * 100).toLocaleString(locale, { maximumFractionDigits: 0 })} cm`;
  if (gsd < 1000) return `${Math.round(gsd).toLocaleString(locale)} m`;
  return `${(gsd / 1000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

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
    const label = formatGsd(properties.gsd, properties.crs, locale);
    if (label) specs.push({ icon: Ruler, label });
  }

  if (isVrt && properties.vrt_type) {
    specs.push({ icon: Combine, label: capitalizeVrtType(properties.vrt_type) });
  }

  if (isVrt && properties.source_count != null) {
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
  if (properties.description && properties.description.trim() !== '') {
    return properties.description;
  }
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
        gsd: properties.gsd != null ? formatGsd(properties.gsd, properties.crs, locale) : '',
      });
    case 'vrt_dataset':
      return t('card.autoDesc.vrt', {
        vrtType: properties.vrt_type ? capitalizeVrtType(properties.vrt_type) : '',
        count: properties.source_count ?? 0,
      });
    case 'table':
      return t('card.autoDesc.table', { count: properties.feature_count ?? 0 });
    default:
      break;
  }
  return t('card.autoDesc.fallback');
}

export const SearchResultCard = memo(function SearchResultCard({ feature }: { feature: OGCRecordResponse }) {
  const { t, i18n } = useTranslation('search');
  const { properties } = feature;
  const recordType = properties.record_type ?? 'vector_dataset';
  const isCollection = recordType === 'collection';
  const isTable = recordType === 'table';
  const linkPath = isCollection ? `/collections/${feature.id}` : `/datasets/${feature.id}`;
  const bbox = extractBbox(feature);

  // Quicklook: only render when the backend confirms a quicklook exists.
  // Uses native <img loading="lazy"> so the browser can cache the image
  // (Cache-Control: public, max-age=3600) and the search page no longer
  // fires 20+ parallel authenticated fetches.
  // NOTE: <img> tags cannot send Authorization headers, so quicklooks for
  // non-public datasets require a dedicated download-token endpoint (future).
  //
  // SP-07: the backend's has_quicklook flag is set when quicklook_256_uri is
  // assigned at ingest, but does NOT verify file existence. When the Celery
  // thumbnail-generation task fails silently the request 404s and pollutes
  // the console. Skip the <img> for any id that already 404'd this session.
  const featureId = feature.id as string;
  const quicklookId =
    !isCollection && !isTable && properties.has_quicklook && !isQuicklookKnownMissing(featureId)
      ? featureId
      : null;
  const quicklookUrl = quicklookId
    ? `/api/datasets/${quicklookId}/quicklook?size=256`
    : null;

  // Provenance (for non-collection types)
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

  // Footer status badge — only for non-collection, non-published records
  const showStatusBadge = !isCollection && !!recordStatus && recordStatus !== 'published';

  return (
    <Link to={linkPath} className="group block" data-testid="search-result-card">
      <Card className="cursor-pointer overflow-hidden border-border/50 bg-card/95 py-0 transition-[transform,color,background-color,box-shadow,border-color] duration-200 ease-out group-hover:-translate-y-0.5 group-hover:border-primary/20 group-hover:shadow-md">
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
                <span className="block text-base font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-1">
                  {properties.title}
                </span>
                {properties.description && (
                  <p className="text-[13px] leading-5 text-muted-foreground/80 line-clamp-1">
                    {properties.description}
                  </p>
                )}
              </div>
            ) : (
              /* Dataset: grid with fixed square thumbnail */
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_132px] xl:grid-cols-[minmax(0,1fr)_148px]">
                <div className="min-w-0 flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <RecordTypeBadge recordType={recordType} />
                    {properties.keywords?.includes('synthetic') && (
                      <Badge variant="outline" className={`text-xs ${syntheticBadgeColor}`}>
                        {t('card.testData', { defaultValue: 'Test Data' })}
                      </Badge>
                    )}
                  </div>
                  <span className="block text-base font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-2">
                    {properties.title}
                  </span>
                  {sourceOrganization && (
                    <p
                      className="text-[12px] leading-4 text-muted-foreground/70 line-clamp-1"
                      data-testid="dataset-card-source"
                      title={sourceOrganization}
                    >
                      {sourceOrganization}
                    </p>
                  )}
                  <p
                    className="text-[13px] leading-5 text-muted-foreground/85 line-clamp-2"
                    data-testid="dataset-card-description"
                  >
                    {buildAutoDescription(properties, t, i18n.language)}
                  </p>

                  {/* Specs row */}
                  {cardSpecs.length > 0 && (
                    <div className="flex flex-wrap gap-x-3 gap-y-1" data-testid="dataset-card-specs">
                      {cardSpecs.map((item, index) => (
                        <span key={item.label} className="inline-flex items-center gap-1 text-xs font-medium font-mono tracking-wide text-muted-foreground">
                          {index > 0 && (
                            <span className="me-1 text-muted-foreground/40">&middot;</span>
                          )}
                          <item.icon className="size-3 shrink-0" aria-hidden="true" />
                          {item.label}
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
                          className="inline-flex items-center rounded-full border border-border/30 bg-muted/15 px-2.5 py-0.5 text-[11px] text-muted-foreground/70"
                        >
                          {tag}
                        </span>
                      ))}
                      {displayKeywords.length > 3 && (
                        <span className="self-center text-xs text-muted-foreground/80">
                          {t('card.moretags', { count: displayKeywords.length - 3 })}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Updated time */}
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    {hasMissingProvenance ? (
                      <span data-testid="dataset-card-updated-attribution" title={createdTime.absolute}>
                        {properties.created
                          ? t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })
                          : noUpdateMetadataLabel}
                      </span>
                    ) : (
                      <span
                        data-testid="dataset-card-updated-attribution"
                        title={updatedAbsolute}
                      >
                        {t('card.updatedFallback', { time: updatedRelative, defaultValue: 'Updated {{time}}' })}
                      </span>
                    )}
                    {showStatusBadge && recordStatus && (
                      <Badge
                        variant={statusVariants[recordStatus] ?? 'outline'}
                        className={statusStyles[recordStatus] ?? 'text-xs'}
                      >
                        {t(`card.status.${recordStatus}`, {
                          defaultValue: recordStatus.charAt(0).toUpperCase() + recordStatus.slice(1),
                        })}
                      </Badge>
                    )}
                  </div>
                </div>

                {/* Right: 160x160 square preview — hidden on mobile */}
                <div className="hidden md:flex md:items-start">
                  <div className="size-[132px] shrink-0 overflow-hidden rounded-lg border border-border/40 xl:size-[148px]">
                    {isTable ? (
                      <div
                        className="flex size-[132px] flex-col items-center justify-center gap-2 bg-type-table-bg text-type-table xl:size-[148px]"
                        role="img"
                        aria-label={
                          properties.column_count
                            ? t('card.tableAriaLabel', { rows: properties.feature_count ?? 0, cols: properties.column_count })
                            : t('card.tableAriaLabelNoCols', { rows: properties.feature_count ?? 0 })
                        }
                      >
                        <Table2
                          className="h-10 w-10 opacity-80"
                          aria-hidden="true"
                          data-testid="table-thumbnail-icon"
                        />
                        <span className="text-xs font-medium font-mono tabular-nums tracking-wide">
                          {t('card.tableRows', { count: properties.feature_count ?? 0 })}
                          {properties.column_count ? ` · ${t('card.tableCols', { count: properties.column_count })}` : ''}
                        </span>
                      </div>
                    ) : quicklookUrl && quicklookId ? (
                      <img
                        src={quicklookUrl}
                        loading="lazy"
                        alt={t('datasetCard.quicklookAlt', { name: properties.title })}
                        className="size-[132px] object-cover xl:size-[148px]"
                        onError={() => {
                          // SP-07: cache the failure for the session so
                          // subsequent renders / reloads skip the 404.
                          markQuicklookMissing(quicklookId);
                        }}
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
                {properties.created ? (
                  <span
                    data-testid="dataset-card-updated-attribution"
                    title={createdTime.absolute}
                  >
                    {t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })}
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
