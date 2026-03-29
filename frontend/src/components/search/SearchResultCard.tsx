import { Link } from 'react-router';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { ImageOff, Loader2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { RecordTypeBadge } from './RecordTypeBadge';
import { formatProvenanceTime } from '@/lib/provenance-attribution';
import { extractBbox } from '@/lib/geo-utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { useQuicklook } from '@/hooks/use-quicklook';
import { ingestionStatusColors, syntheticBadgeColor } from '@/lib/status-colors';
import type { OGCRecordResponse } from '@/types/api';

function formatGsd(gsd: number, crs?: string | null): string {
  // For geographic CRS (degree-based), don't show GSD — it's meaningless as a distance
  if (crs && /^EPSG:4326$/i.test(crs)) return '';
  // Sub-meter
  if (gsd < 1) return `${(gsd * 100).toFixed(0)} cm`;
  if (gsd < 1000) return `${Math.round(gsd)} m`;
  return `${(gsd / 1000).toFixed(1)} km`;
}

function capitalizeVrtType(vrtType: string): string {
  // 'mosaic' -> 'Mosaic', 'band_stack' -> 'Band Stack'
  return vrtType
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function buildCardSpecs(
  properties: OGCRecordResponse['properties'],
  t: TFunction<'search'>,
): string[] {
  const recordType = properties.record_type ?? 'vector_dataset';
  const isRaster = recordType === 'raster_dataset';
  const isVrt = recordType === 'vrt_dataset';
  const specs: string[] = [];

  if (!isRaster && !isVrt && properties.geometry_type) {
    specs.push(getGeometryTypeLabel(t, properties.geometry_type));
  }

  if (isRaster && properties.band_count != null) {
    specs.push(t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' }));
  }

  if (isRaster && properties.gsd != null) {
    const label = formatGsd(properties.gsd, properties.crs);
    if (label) specs.push(label);
  }

  if (isVrt && properties.vrt_type) {
    specs.push(capitalizeVrtType(properties.vrt_type));
  }

  if (isVrt && properties.source_count != null) {
    specs.push(t('card.sourceCount', { count: properties.source_count, defaultValue: '{{count}} sources' }));
  }

  if (isVrt && properties.band_count != null) {
    specs.push(t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' }));
  }

  if (!isRaster && !isVrt && properties.feature_count != null) {
    const isTable = recordType === 'table';
    specs.push(isTable
      ? t('card.rowCount', { count: properties.feature_count })
      : t('card.featureCount', { count: properties.feature_count }));
  }

  if (properties.crs) specs.push(properties.crs);

  return specs;
}

export function SearchResultCard({ feature }: { feature: OGCRecordResponse }) {
  const { t, i18n } = useTranslation('search');
  const { properties } = feature;
  const recordType = properties.record_type ?? 'vector_dataset';
  const isCollection = recordType === 'collection';
  const isTable = recordType === 'table';
  const linkPath = isCollection ? `/collections/${feature.id}` : `/datasets/${feature.id}`;
  const bbox = extractBbox(feature);

  // Quicklook: only fetch for record types that support visual previews.
  const quicklookId = !isCollection && !isTable ? (feature.id as string) : null;
  const { src: quicklookSrc, isLoading: qlLoading, isError: qlError } = useQuicklook(quicklookId);

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
  const cardSpecs = isCollection ? [] : buildCardSpecs(properties, t);
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

  return (
    <Link to={linkPath} className="group block" data-testid="search-result-card">
      <Card className="cursor-pointer overflow-hidden border-border/50 bg-card/95 py-0 transition-[transform,color,background-color,box-shadow,border-color] duration-200 ease-out group-hover:-translate-y-0.5 group-hover:border-primary/20 group-hover:shadow-md">
        <div className="p-4 sm:p-5">
          <div className="flex flex-col gap-3">

            {/* Band 1 — Header */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_80px]">
              {/* Left: badges, title, source */}
              <div className="min-w-0 flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <RecordTypeBadge recordType={recordType} />

                  {isCollection && properties.dataset_count != null && (
                    <Badge variant="secondary" className="text-xs">
                      {t('collection.datasetCount', { count: properties.dataset_count, defaultValue: '{{count}} datasets' })}
                    </Badge>
                  )}

                  {!isCollection && properties.keywords?.includes('synthetic') && (
                    <Badge variant="outline" className={`text-xs ${syntheticBadgeColor}`}>
                      {t('card.testData', { defaultValue: 'Test Data' })}
                    </Badge>
                  )}
                </div>

                <span className="block text-lg font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-2">
                  {properties.title}
                </span>

                {!isCollection && sourceOrganization && (
                  <p
                    className="max-w-3xl text-[13px] leading-5 text-muted-foreground/90 line-clamp-2"
                    data-testid="dataset-card-source"
                    title={sourceOrganization}
                  >
                    {sourceOrganization}
                  </p>
                )}

                {isCollection && properties.description && (
                  <p className="max-w-3xl text-sm leading-6 text-muted-foreground line-clamp-2">
                    {properties.description}
                  </p>
                )}
              </div>

              {/* Right: 80x80 preview, hidden on mobile, hidden for collections */}
              {!isCollection && (
                <div className="hidden md:block">
                  <div className="h-[80px] w-[80px] overflow-hidden rounded-lg border border-border/40">
                    {isTable ? (
                      <div className="flex h-[80px] w-[80px] flex-col items-center justify-center gap-1 bg-muted/20 text-muted-foreground">
                        <ImageOff className="h-5 w-5 opacity-45" />
                        <span className="text-xs">{t('datasetCard.previewUnavailable')}</span>
                      </div>
                    ) : quicklookSrc ? (
                      <img
                        src={quicklookSrc}
                        alt={t('datasetCard.quicklookAlt', { name: properties.title })}
                        className="h-[80px] w-[80px] object-cover"
                      />
                    ) : qlLoading ? (
                      <div className="flex h-[80px] w-[80px] items-center justify-center bg-muted/25">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    ) : qlError ? (
                      <div className="flex h-[80px] w-[80px] flex-col items-center justify-center gap-1 bg-muted/25 text-muted-foreground">
                        <ImageOff className="h-5 w-5 opacity-50" />
                      </div>
                    ) : (
                      <BBoxPreview bbox={bbox} />
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Band 2 — Facts (specs row) */}
            {!isCollection && cardSpecs.length > 0 && (
              <div className="flex flex-wrap gap-1.5" data-testid="dataset-card-specs">
                {cardSpecs.map((item) => (
                  <span
                    key={item}
                    className="inline-flex items-center rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground/90"
                  >
                    {item}
                  </span>
                ))}
              </div>
            )}

            {/* Band 3 — Tags */}
            {!isCollection && displayKeywords.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {displayKeywords.slice(0, 3).map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground/90"
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

            {/* Band 4 — Footer */}
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              {/* Left: updated time */}
              {isCollection ? (
                properties.created ? (
                  <span
                    data-testid="dataset-card-updated-attribution"
                    title={createdTime.absolute}
                  >
                    {t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })}
                  </span>
                ) : (
                  <span />
                )
              ) : hasMissingProvenance ? (
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

              {/* Right: status badge */}
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
        </div>
      </Card>
    </Link>
  );
}
