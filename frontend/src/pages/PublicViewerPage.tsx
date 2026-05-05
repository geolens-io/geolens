import { useCallback, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { ViewerMap } from '@/components/viewer/ViewerMap';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { MapTitlePill } from '@/components/map/MapTitlePill';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { Clock, MapPinOff } from 'lucide-react';
import { ApiError } from '@/api/client';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { AppFooter } from '@/components/layout/AppFooter';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { MapErrorBoundary } from '@/components/error';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { Button } from '@/components/ui/button';

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
  const showFooterBranding = !isEnterprise || branding?.show_badge !== false;
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
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_hsl(var(--muted))_0,_transparent_55%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted))/0.45)] px-6">
        <div className="flex w-full max-w-xl flex-col items-center rounded-2xl border bg-background/95 p-8 text-center shadow-xl backdrop-blur">
          {isExpired ? (
            <>
              <Clock className="size-10 text-muted-foreground" />
              <div className="mt-4 space-y-2 text-center">
                <h1 className="text-2xl font-semibold text-foreground">{t('viewer.linkExpired')}</h1>
                <p className="mx-auto max-w-md text-sm text-muted-foreground">
                  {t('viewer.linkExpiredDescription')}
                </p>
                <p className="mx-auto max-w-md text-sm text-muted-foreground">
                  {t('viewer.linkRecovery', {
                    defaultValue: 'Ask the map owner for a fresh share link if you still need access.',
                  })}
                </p>
              </div>
            </>
          ) : (
            <>
              <MapPinOff className="size-10 text-muted-foreground" />
              <div className="mt-4 space-y-2 text-center">
                <h1 className="text-2xl font-semibold text-foreground">{t('viewer.mapNotFound')}</h1>
                <p className="mx-auto max-w-md text-sm text-muted-foreground">
                  {t('viewer.mapNotFoundDescription')}
                </p>
                <p className="mx-auto max-w-md text-sm text-muted-foreground">
                  {t('viewer.linkRecovery', {
                    defaultValue: 'Ask the map owner for a fresh share link if you still need access.',
                  })}
                </p>
              </div>
            </>
          )}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Button asChild>
              <Link to="/">
                {t('viewer.browseCatalog', { defaultValue: 'Browse catalog' })}
              </Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/login">
                {t('viewer.signIn', { defaultValue: 'Sign in' })}
              </Link>
            </Button>
          </div>
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
      <MapErrorBoundary>
        <ViewerMap
          layers={data.layers}
          basemapStyle={basemapId ?? data.basemap_style}
          basemapOverride={basemapId !== null}
          showBasemapLabels={data.show_basemap_labels ?? true}
          terrainConfig={data.terrain_config ?? null}
          initialViewState={viewState}
          visibleLayers={visibleLayers}
          apiKey={apiKey}
          embedToken={embedToken}
        />
      </MapErrorBoundary>

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

      {!isEmbed && (
        <AppFooter
          showBranding={showFooterBranding}
          className="pointer-events-none absolute inset-x-0 bottom-0 z-10 hidden min-[400px]:block px-3 pb-2 text-[10px] text-muted-foreground/80"
          navClassName="pointer-events-auto mx-auto inline-flex max-w-full rounded-full border border-border/50 bg-background/75 px-3 py-1.5 shadow-sm backdrop-blur-sm"
        />
      )}
    </main>
  );
}
