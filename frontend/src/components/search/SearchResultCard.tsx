import { Link } from 'react-router';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { FolderOpen, ImageOff, Loader2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { RecordTypeBadge } from './RecordTypeBadge';
import { formatProvenanceTime, resolveProvenanceIdentity } from '@/lib/provenance-attribution';
import { extractBbox } from '@/lib/geo-utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { useQuicklook } from '@/hooks/use-quicklook';
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
    specs.push(t('card.featureCount', { count: properties.feature_count }));
  }

  if (properties.crs) specs.push(properties.crs);

  return specs;
}

export function SearchResultCard({ feature }: { feature: OGCRecordResponse }) {
  const { t, i18n } = useTranslation('search');
  const { properties } = feature;
  const recordType = properties.record_type ?? 'vector_dataset';
  const isCollection = recordType === 'collection';
  const linkPath = isCollection ? `/collections/${feature.id}` : `/datasets/${feature.id}`;
  const bbox = extractBbox(feature);

  // Quicklook: only fetch for non-collection types
  const quicklookId = isCollection ? null : (feature.id as string);
  const { src: quicklookSrc, isLoading: qlLoading, isError: qlError } = useQuicklook(quicklookId);

  // Provenance (for non-collection types)
  const neverEditedLabel = t('card.neverEdited', { defaultValue: 'Never' });
  const updatedByLabel = t('card.updatedBy', { defaultValue: 'Updated by' });
  const noUpdateMetadataLabel = t('card.noUpdateMetadata', { defaultValue: 'No update metadata' });
  const unknownIdentityLabel = t('card.unknown', { defaultValue: 'Unknown' });

  const updatedByIdentity = resolveProvenanceIdentity(properties.updated_by_display, {
    unknown: unknownIdentityLabel,
    restricted: t('card.restricted', { defaultValue: 'Restricted user' }),
    system: t('card.system', { defaultValue: 'System' }),
  });
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
    (!properties.updated_by_display || updatedByIdentity === unknownIdentityLabel);

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

  return (
    <Link to={linkPath} className="group block" data-testid="search-result-card">
      <Card className="cursor-pointer overflow-hidden border-border/60 bg-card/90 py-0 transition-[transform,color,background-color,box-shadow,border-color] duration-200 ease-out group-hover:-translate-y-0.5 group-hover:border-primary/20 group-hover:shadow-lg">
        <div className="flex flex-col md:grid md:grid-cols-[minmax(0,1fr)_14rem]">
          <div className="min-w-0 p-4 sm:p-5">
            <div className="flex flex-col gap-3.5">
              <div className="flex flex-wrap items-center gap-2">
                {/* Status badges (non-collection only) */}
                {!isCollection && recordStatus && recordStatus !== 'published' && (() => {
                  const statusStyles: Record<string, string> = {
                    draft: 'text-xs border-amber-500/50 text-amber-600 dark:text-amber-400',
                    ready: 'text-xs border-blue-500/50 text-blue-600 dark:text-blue-400',
                    internal: 'text-xs border-slate-500/50 text-slate-600 dark:text-slate-400',
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
                  const label = t(`card.status.${recordStatus}`, {
                    defaultValue: recordStatus.charAt(0).toUpperCase() + recordStatus.slice(1),
                  });
                  return (
                    <Badge
                      variant={statusVariants[recordStatus] ?? 'outline'}
                      className={statusStyles[recordStatus] ?? 'text-xs'}
                    >
                      {label}
                    </Badge>
                  );
                })()}
                {!isCollection && properties.keywords?.includes('synthetic') && (
                  <Badge variant="outline" className="text-xs border-purple-500/50 text-purple-600 dark:text-purple-400">
                    {t('card.testData', { defaultValue: 'Test Data' })}
                  </Badge>
                )}

                <RecordTypeBadge recordType={recordType} />

                {isCollection && properties.dataset_count != null && (
                  <Badge variant="secondary" className="text-xs">
                    {t('collection.datasetCount', { count: properties.dataset_count, defaultValue: '{{count}} datasets' })}
                  </Badge>
                )}

              </div>

              <div className="space-y-2">
                <span className="block text-lg font-semibold leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-2">
                  {properties.title}
                </span>

                {!isCollection && sourceOrganization && (
                  <p
                    className="max-w-3xl text-sm leading-6 text-muted-foreground line-clamp-2"
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

              {!isCollection && cardSpecs.length > 0 && (
                <div className="flex flex-wrap gap-1.5" data-testid="dataset-card-specs">
                  {cardSpecs.map((item) => (
                    <span
                      key={item}
                      className="inline-flex items-center rounded-full border border-border/60 bg-muted/45 px-2.5 py-1 text-xs font-medium text-muted-foreground"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              )}

              {!isCollection && displayKeywords.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {displayKeywords.slice(0, 2).map((tag) => (
                    <Badge key={tag} variant="outline" className="border-border/60 bg-background/70 text-xs font-normal text-muted-foreground">
                      {tag}
                    </Badge>
                  ))}
                  {displayKeywords.length > 2 && (
                    <span className="self-center text-xs text-muted-foreground">
                      {t('card.moretags', { count: displayKeywords.length - 2 })}
                    </span>
                  )}
                </div>
              )}

              {isCollection ? (
                !properties.description && properties.created ? (
                  <div className="text-xs text-muted-foreground">
                    {t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })}
                  </div>
                ) : null
              ) : (
                <div className="flex flex-wrap items-center gap-2.5 text-xs text-muted-foreground">
                  {hasMissingProvenance ? (
                    <span data-testid="dataset-card-updated-attribution" title={createdTime.absolute}>
                      {properties.created
                        ? t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })
                        : noUpdateMetadataLabel}
                    </span>
                  ) : (
                    <span
                      className="inline-flex min-w-0 max-w-full flex-wrap items-center gap-1.5"
                      data-testid="dataset-card-updated-attribution"
                    >
                      <span className="shrink-0">{updatedByLabel}</span>
                      <span className="max-w-[14rem] truncate" title={updatedByIdentity}>
                        {updatedByIdentity}
                      </span>
                      <span aria-hidden className="shrink-0">&#8226;</span>
                      <span className="shrink-0" title={updatedAbsolute}>
                        {updatedRelative}
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="hidden border-t border-border/50 bg-muted/20 p-4 md:flex md:min-h-full md:border-l md:border-t-0">
            <div className="flex w-full items-center justify-center overflow-hidden rounded-[20px] border border-border/50 bg-background/60">
              {isCollection ? (
                <div className="flex h-[140px] w-full items-center justify-center bg-muted/25">
                  <FolderOpen className="h-8 w-8 text-muted-foreground/50" />
                </div>
              ) : quicklookSrc ? (
                <img
                  src={quicklookSrc}
                  alt={t('datasetCard.quicklookAlt', { name: properties.title })}
                  className="h-[140px] w-full object-cover"
                />
              ) : qlLoading ? (
                <div className="flex h-[140px] w-full items-center justify-center bg-muted/25">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : qlError ? (
                <div className="flex h-[140px] w-full flex-col items-center justify-center gap-1 bg-muted/25 text-muted-foreground">
                  <ImageOff className="h-5 w-5 opacity-50" />
                  <span className="text-xs">{t('datasetCard.previewUnavailable')}</span>
                </div>
              ) : (
                <BBoxPreview bbox={bbox} />
              )}
            </div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
