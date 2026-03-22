import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FolderOpen, ImageOff, Loader2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { QualityBadge } from './QualityBadge';
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

export function SearchResultCard({ feature }: { feature: OGCRecordResponse }) {
  const { t, i18n } = useTranslation('search');
  const { properties } = feature;
  const recordType = properties.record_type ?? 'vector_dataset';
  const isCollection = recordType === 'collection';
  const isRaster = recordType === 'raster_dataset';
  const isVrt = recordType === 'vrt_dataset';
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

  return (
    <Link to={linkPath} className="group block">
      <Card className="flex flex-col sm:flex-row gap-0 py-0 overflow-hidden cursor-pointer group-hover:shadow-md group-hover:border-primary/20 group-hover:bg-accent/50 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out">
        {/* Content section */}
        <div className="flex-1 p-3 min-w-0">
          <span className="text-lg font-semibold text-foreground group-hover:text-primary transition-colors line-clamp-2 sm:line-clamp-1">
            {properties.title}
          </span>

          {/* Row 2: type badge + status badges + inline metadata */}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
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

            {/* Type-specific inline metadata */}
            {isCollection ? (
              properties.dataset_count != null && (
                <Badge variant="secondary" className="text-xs">
                  {t('collection.datasetCount', { count: properties.dataset_count, defaultValue: '{{count}} datasets' })}
                </Badge>
              )
            ) : (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                {/* Vector: geometry type */}
                {!isRaster && !isVrt && properties.geometry_type && (
                  <>{getGeometryTypeLabel(t, properties.geometry_type)}</>
                )}
                {/* Raster: band count */}
                {isRaster && properties.band_count != null && (
                  <>{t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' })}</>
                )}
                {/* Raster: gsd */}
                {isRaster && properties.gsd != null && (() => {
                  const label = formatGsd(properties.gsd, properties.crs);
                  return label ? <><span aria-hidden>·</span>{label}</> : null;
                })()}
                {/* VRT: vrt_type label */}
                {isVrt && properties.vrt_type && (
                  <>{capitalizeVrtType(properties.vrt_type)}</>
                )}
                {/* VRT: source count */}
                {isVrt && properties.source_count != null && (
                  <><span aria-hidden>·</span>{t('card.sourceCount', { count: properties.source_count, defaultValue: '{{count}} sources' })}</>
                )}
                {/* VRT: band count */}
                {isVrt && properties.band_count != null && (
                  <><span aria-hidden>·</span>{t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' })}</>
                )}
                {/* Vector: feature count */}
                {!isRaster && !isVrt && properties.feature_count != null && (
                  <><span aria-hidden>·</span>{t('card.featureCount', { count: properties.feature_count })}</>
                )}
                {/* CRS */}
                {properties.crs && (
                  <><span aria-hidden>·</span>{properties.crs}</>
                )}
                {/* Source organization */}
                {properties.source_organization && (
                  <><span aria-hidden>·</span>{properties.source_organization}</>
                )}
              </span>
            )}

            {!isCollection && (
              <QualityBadge score={properties.quality_detail?.overall ?? null} />
            )}
          </div>

          {/* Row 3: tags (non-collection only, max 2) */}
          {!isCollection && (() => {
            const displayKeywords = properties.keywords?.filter(
              (k) => k !== 'synthetic' && k !== 'perf-seed'
            ) ?? [];
            return displayKeywords.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {displayKeywords.slice(0, 2).map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs font-normal text-muted-foreground">
                    {tag}
                  </Badge>
                ))}
                {displayKeywords.length > 2 && (
                  <span className="text-xs text-muted-foreground self-center">
                    {t('card.moretags', { count: displayKeywords.length - 2 })}
                  </span>
                )}
              </div>
            ) : null;
          })()}

          {/* Row 4: Footer */}
          {isCollection ? (
            // Collection footer: description or created date
            properties.description ? (
              <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
                {properties.description}
              </p>
            ) : properties.created ? (
              <div className="mt-1.5 text-xs text-muted-foreground">
                {t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })}
              </div>
            ) : null
          ) : (
            // Dataset footer: provenance attribution
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              {hasMissingProvenance ? (
                <span data-testid="dataset-card-updated-attribution" title={createdTime.absolute}>
                  {properties.created
                    ? t('card.updatedFallback', { time: createdTime.relative, defaultValue: 'Updated {{time}}' })
                    : noUpdateMetadataLabel}
                </span>
              ) : (
                <span
                  className="inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap"
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

        {/* Preview column (right side, hidden on mobile) */}
        <div className="hidden sm:block sm:w-40 sm:flex-shrink-0 sm:border-l border-border/50 bg-muted/20 sm:p-3">
          {isCollection ? (
            // Collection: folder icon placeholder
            <div className="flex items-center justify-center h-[120px] w-full bg-muted/30 rounded-md">
              <FolderOpen className="h-8 w-8 text-muted-foreground/50" />
            </div>
          ) : quicklookSrc ? (
            <img
              src={quicklookSrc}
              alt={t('datasetCard.quicklookAlt', { name: properties.title })}
              className="w-full h-full object-cover rounded-md"
            />
          ) : qlLoading ? (
            <div className="flex items-center justify-center h-[120px] w-full bg-muted/30 rounded-md">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : qlError ? (
            <div className="flex flex-col items-center justify-center h-[120px] w-full bg-muted/30 rounded-md text-muted-foreground gap-1">
              <ImageOff className="h-5 w-5 opacity-50" />
              <span className="text-xs">{t('datasetCard.previewUnavailable')}</span>
            </div>
          ) : (
            <BBoxPreview bbox={bbox} />
          )}
        </div>
      </Card>
    </Link>
  );
}
