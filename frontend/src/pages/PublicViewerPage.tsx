import { useCallback, useState } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/hooks/use-viewer-layers';
import { ViewerMap } from '@/components/viewer/ViewerMap';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { MapTitlePill } from '@/components/map/MapTitlePill';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { Clock, MapPinOff } from 'lucide-react';
import { ApiError } from '@/api/client';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';

function parseCenter(raw: string | null): { lng: number; lat: number } | null {
  if (!raw) return null;
  const parts = raw.split(',');
  if (parts.length !== 2) return null;
  const lng = parseFloat(parts[0]);
  const lat = parseFloat(parts[1]);
  if (isNaN(lng) || isNaN(lat)) return null;
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return null;
  return { lng, lat };
}

function parseZoom(raw: string | null): number | null {
  if (!raw) return null;
  const z = parseFloat(raw);
  if (isNaN(z) || z < 0 || z > 24) return null;
  return z;
}

export function PublicViewerPage() {
  const { t } = useTranslation('common');
  useDocumentTitle(t('common:pageTitle.sharedMap'));
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showBadge = !isEnterprise || branding?.show_badge !== false;
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  const isEmbed = searchParams.get('embed') === 'true';
  const apiKey = searchParams.get('api_key') ?? undefined;
  const embedToken = searchParams.get('et') ?? undefined;
  const zoomParam = searchParams.get('zoom');
  const centerParam = searchParams.get('center');
  const legendParam = searchParams.get('legend');

  const { data, isLoading, isError, error } = useSharedMap(token, apiKey);

  const effectiveShowLegend = legendParam !== null ? legendParam === 'true' : !isEmbed;

  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(data?.layers, { showLegend: effectiveShowLegend });

  const [basemapId, setBasemapId] = useState<string | null>(null);
  const handleLegendToggle = useCallback(() => setIsLegendOpen((prev) => !prev), [setIsLegendOpen]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center w-full h-screen bg-muted">
        <LoadingState message={t('viewer.loading')} />
      </div>
    );
  }

  if (isError || !data) {
    const isExpired = error instanceof ApiError && error.status === 410;
    return (
      <div className="flex items-center justify-center w-full h-screen bg-muted">
        <div className="flex flex-col items-center gap-3 text-center">
          {isExpired ? (
            <>
              <Clock className="size-10 text-muted-foreground" />
              <h1 className="text-2xl font-semibold text-foreground">{t('viewer.linkExpired')}</h1>
              <p className="text-sm text-muted-foreground max-w-sm">
                {t('viewer.linkExpiredDescription')}
              </p>
            </>
          ) : (
            <>
              <MapPinOff className="size-10 text-muted-foreground" />
              <h1 className="text-2xl font-semibold text-foreground">{t('viewer.mapNotFound')}</h1>
              <p className="text-sm text-muted-foreground max-w-sm">
                {t('viewer.mapNotFoundDescription')}
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  const parsedCenter = parseCenter(centerParam);
  const parsedZoom = parseZoom(zoomParam);

  const viewState = {
    center_lng: parsedCenter?.lng ?? data.center_lng,
    center_lat: parsedCenter?.lat ?? data.center_lat,
    zoom: parsedZoom ?? data.zoom,
    bearing: data.bearing,
    pitch: data.pitch,
  };

  return (
    <main id="map-viewport" className="w-full h-screen relative overflow-hidden">
      {/* Full-viewport map */}
      <ViewerMap
        layers={data.layers}
        basemapStyle={basemapId ?? data.basemap_style}
        basemapOverride={basemapId !== null}
        showBasemapLabels={data.show_basemap_labels ?? true}
        initialViewState={viewState}
        visibleLayers={visibleLayers}
        apiKey={apiKey}
        embedToken={embedToken}
      />

      <MapTitlePill name={data.name} description={data.description} />

      {/* Legend overlay */}
      {effectiveShowLegend && (
        <LayerLegend
          layers={data.layers}
          visibleLayers={visibleLayers}
          onToggleVisibility={handleToggleVisibility}
          isOpen={isLegendOpen}
          onToggle={handleLegendToggle}
        />
      )}

      {/* Basemap switcher */}
      {!isEmbed && (
        <BasemapToggle
          value={basemapId ?? data.basemap_style}
          onChange={setBasemapId}
          title={t('viewer.changeBasemap')}
          className="absolute bottom-8 left-3 z-10"
        />
      )}

      {/* Powered by GeoLens badge */}
      {showBadge && (
        <div className="absolute bottom-2 right-2 z-10 hidden min-[400px]:block">
          <a
            href="https://github.com/geolens-io/geolens"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-muted-foreground/70 hover:text-muted-foreground bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5 transition-colors"
          >
            {t('viewer.poweredBy')}
          </a>
        </div>
      )}
    </main>
  );
}
