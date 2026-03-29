import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ImageOff, Loader2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { RecordTypeBadge } from './RecordTypeBadge';
import { formatProvenanceTime, resolveProvenanceIdentity } from '@/lib/provenance-attribution';
import { extractBbox } from '@/lib/geo-utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { useAuthStore } from '@/stores/auth-store';
import { ingestionStatusColors, syntheticBadgeColor } from '@/lib/status-colors';
import type { OGCRecordResponse } from '@/types/api';

export function DatasetCard({ feature }: { feature: OGCRecordResponse }) {
  const { t, i18n } = useTranslation('search');
  const { properties } = feature;
  const bbox = extractBbox(feature);
  const isRaster = properties.record_type === 'raster_dataset';
  const isVrt = properties.record_type === 'vrt_dataset';
  const hasQuicklook = true; // All dataset types now have server-rendered quicklooks
  const [imgError, setImgError] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [quicklookSrc, setQuicklookSrc] = useState<string | null>(null);
  const blobUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (!hasQuicklook || imgError) return;
    let revoked = false;
    setIsLoading(true);
    const token = useAuthStore.getState().token;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    fetch(`/api/datasets/${feature.id}/quicklook?size=256`, { headers })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.blob();
      })
      .then((blob) => {
        if (revoked) return;
        if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = URL.createObjectURL(blob);
        setQuicklookSrc(blobUrlRef.current);
        setIsLoading(false);
      })
      .catch(() => {
        if (!revoked) {
          setImgError(true);
          setIsLoading(false);
        }
      });
    return () => {
      revoked = true;
      setIsLoading(false);
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [hasQuicklook, feature.id, imgError]);
  const recordStatus = properties.record_status;
  const neverEditedLabel = t('card.neverEdited', { defaultValue: 'Never' });
  const updatedByLabel = t('card.updatedBy', { defaultValue: 'Updated by' });
  const noUpdateMetadataLabel = t('card.noUpdateMetadata', {
    defaultValue: 'No update metadata',
  });
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

  return (
    <Link to={`/datasets/${feature.id}`} className="group block">
      <Card className="flex flex-col sm:flex-row gap-0 py-0 overflow-hidden cursor-pointer group-hover:shadow-md group-hover:border-primary/20 group-hover:bg-accent/50 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out">
        {/* Metadata section */}
        <div className="flex-1 p-3 min-w-0">
          <span className="text-lg font-semibold text-foreground group-hover:text-primary transition-colors line-clamp-2 sm:line-clamp-1">
            {properties.title}
          </span>

          {properties.description && (
            <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
              {properties.description}
            </p>
          )}

          {/* Line 2: type badge + status badges */}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {recordStatus && recordStatus !== 'published' && (() => {
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
            {properties.keywords?.includes('synthetic') && (
              <Badge variant="outline" className={`text-xs ${syntheticBadgeColor}`}>
                {t('card.testData', { defaultValue: 'Test Data' })}
              </Badge>
            )}
            <RecordTypeBadge recordType={properties.record_type ?? 'vector_dataset'} />
            {/* Plain text metadata: subtype · count · CRS · completeness */}
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              {!isRaster && !isVrt && properties.geometry_type && (
                <>{getGeometryTypeLabel(t, properties.geometry_type)}</>
              )}
              {(isRaster || isVrt) && properties.band_count != null && (
                <>{t('card.bandCount', { count: properties.band_count, defaultValue: '{{count}} bands' })}</>
              )}
              {!isRaster && !isVrt && properties.feature_count != null && (
                <><span aria-hidden>·</span>{t('card.featureCount', { count: properties.feature_count })}</>
              )}
              {properties.crs && (
                <><span aria-hidden>·</span>{properties.crs}</>
              )}
              {properties.source_organization && (
                <><span aria-hidden>·</span>{properties.source_organization}</>
              )}
            </span>
          </div>

          {/* Line 3: tags (max 2) */}
          {(() => {
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
                <span aria-hidden className="shrink-0">•</span>
                <span className="shrink-0" title={updatedAbsolute}>
                  {updatedRelative}
                </span>
              </span>
            )}
          </div>
        </div>

        {/* BBox / quicklook preview section — hidden on mobile to save vertical space */}
        <div className="hidden sm:block sm:w-40 sm:flex-shrink-0 sm:border-l border-border/50 bg-muted/20 sm:p-3">
          {hasQuicklook && !imgError && quicklookSrc ? (
            <img
              src={quicklookSrc}
              alt={t('datasetCard.quicklookAlt', { name: feature.properties.title })}
              className="w-full h-full object-cover rounded-md"
            />
          ) : hasQuicklook && isLoading ? (
            <div className="flex items-center justify-center h-[120px] w-full bg-muted/30 rounded-md">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : hasQuicklook && imgError ? (
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
