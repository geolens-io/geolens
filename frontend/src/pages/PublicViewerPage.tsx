import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
// Lazy so the map-vendor chunk is deferred until rendering is imminent.
const ViewerMap = lazy(() =>
  import('@/components/viewer/ViewerMap').then((m) => ({ default: m.ViewerMap }))
);
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import { legendFacts, type DrawnLayer } from '@/components/map/legend-facts';
import { MapTitlePill } from '@/components/map/MapTitlePill';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { Clock, MapPinOff } from 'lucide-react';
import { ApiError } from '@/api/client';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { SiteBanner } from '@/components/layout/SiteBanner';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { MapErrorBoundary } from '@/components/error';
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

// Keyed by share token so the basemap choice and drawn layers start fresh
// when the route switches to another map without a remount.
export function PublicViewerPage() {
  const { token } = useParams<{ token: string }>();
  return <PublicViewer key={token} />;
}

function PublicViewer() {
  const { t } = useTranslation('common');
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  const isEmbed = searchParams.get('embed') === 'true';
  const embedToken = searchParams.get('et') ?? undefined;
  const zoomParam = searchParams.get('zoom');
  const centerParam = searchParams.get('center');
  const legendParam = searchParams.get('legend');

  const { data, isLoading, isError, error } = useSharedMap(token, embedToken);
  useDocumentTitle(data?.name || t('common:pageTitle.sharedMap'));

  const [drawnLayers, setDrawnLayers] = useState<ReadonlyMap<string, DrawnLayer>>();

  // An embed keeps colour classes readable without a host opt-in: it opens
  // the legend by default when a shown layer is styled by class. It waits for
  // what the map drew, since a failed cluster fetch falls back to plain points.
  const layers = data?.layers;
  const embedNeedsLegend = useMemo(() => {
    if (!isEmbed || !drawnLayers?.size) return false;
    return createViewerLayerEntries(layers).some(({ layer, key }) => {
      if (!layer.visible || layer.show_in_legend === false) return false;
      const facts = legendFacts(layer, drawnLayers.get(key));
      const classes = [...(facts?.classes ?? []), ...(facts?.cluster?.steps ? [facts.cluster.steps.classes] : [])];
      return classes.some((c) => c.target === 'color');
    });
  }, [isEmbed, layers, drawnLayers]);
  const effectiveShowLegend = legendParam !== null ? legendParam === 'true' : !isEmbed || embedNeedsLegend;

  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(data?.layers, { showLegend: effectiveShowLegend, mapKey: token });

  const [basemapId, setBasemapId] = useState<string | null>(null);
  const handleLegendToggle = useCallback(() => setIsLegendOpen((prev) => !prev), [setIsLegendOpen]);

  // Every branch except embeds shows the site banner, expired and invalid
  // share links included, so maintenance notices reach those visitors.
  if (isLoading) {
    return (
      <div className="flex h-dvh flex-col">
        {!isEmbed && <SiteBanner />}
        <main className="flex min-h-0 w-full flex-1 items-center justify-center bg-muted">
          <LoadingState message={t('viewer.loading')} />
        </main>
      </div>
    );
  }

  if (isError || !data) {
    const isExpired = error instanceof ApiError && error.status === 410;
    return (
      // An h-dvh column like the other branches; SiteBanner + min-h-screen
      // would overflow the viewport by the banner's height.
      <div className="flex h-dvh flex-col">
      {!isEmbed && <SiteBanner />}
      <main className="app-surface-gradient flex min-h-0 flex-1 overflow-y-auto px-6">
        {/* m-auto, not items-center on the parent, so a card taller than the
            viewport scrolls instead of clipping its top */}
        <div role="alert" className="m-auto flex w-full max-w-xl flex-col items-center rounded-2xl border bg-background/95 p-8 text-center shadow-lg backdrop-blur">
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
      </main>
      </div>
    );
  }

  const parsedCenter = parseCenter(centerParam);
  const parsedZoom = parseZoom(zoomParam);
  // A map with no saved view opens fitted to its visible layers, as the Builder
  // does, unless the URL picks the view.
  const fitLayers = data.has_saved_view === false && !parsedCenter && parsedZoom === null;

  const viewState = {
    center_lng: parsedCenter?.lng ?? data.center_lng,
    center_lat: parsedCenter?.lat ?? data.center_lat,
    zoom: parsedZoom ?? data.zoom,
    bearing: data.bearing,
    pitch: data.pitch,
  };

  return (
    // A flex column so the banner takes height from the map viewport instead of
    // pushing it below the fold; embeds never show the host banner.
    <div className="relative flex h-dvh flex-col">
      {!isEmbed && <SiteBanner />}
      <main id="map-viewport" className="w-full min-h-0 flex-1 relative overflow-hidden">
      {/* Full-viewport map */}
      <MapErrorBoundary>
        <Suspense fallback={<LoadingState message={t('viewer.loading')} />}>
          <ViewerMap
            layers={data.layers}
            basemapStyle={basemapId ?? data.basemap_style}
            basemapConfig={data.basemap_config ?? null}
            showBasemapLabels={data.show_basemap_labels ?? true}
            terrainConfig={data.terrain_config ?? null}
            initialViewState={viewState}
            fitLayers={fitLayers}
            visibleLayers={visibleLayers}
            embedToken={embedToken}
            onDrawnChange={setDrawnLayers}
            datasetLinksAllowed={!data.has_non_public_layers}
          />
        </Suspense>
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
          terrainConfig={data.terrain_config ?? null}
          legendTitle={data.legend_title ?? null}
          drawn={drawnLayers}
        />
      )}

      {/* Basemap switcher */}
      {!isEmbed && (
        <BasemapToggle
          value={basemapId ?? data.basemap_style}
          onChange={setBasemapId}
          title={t('viewer.changeBasemap')}
          className="absolute bottom-8 start-3 z-10"
        />
      )}

      </main>

    </div>
  );
}
