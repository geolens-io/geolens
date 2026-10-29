import { lazy, Suspense, useCallback, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
// Lazy so the map-vendor chunk is deferred until rendering is imminent.
const ViewerMap = lazy(() =>
  import('@/components/viewer/ViewerMap').then((m) => ({ default: m.ViewerMap }))
);
import { ViewerChatPanel } from '@/components/viewer/ViewerChatPanel';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import type { DrawnLayer } from '@/components/map/legend-facts';
import { MapTitlePill } from '@/components/map/MapTitlePill';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { MapUnavailableState } from '@/components/map/MapUnavailableState';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { MapErrorBoundary } from '@/components/error';
import { toSharedLayer } from '@/components/viewer/shared-layer';

// Keyed by map id so the basemap choice and drawn layers start fresh when the
// route switches to another map without a remount.
export function PublicMapViewerPage() {
  const { id } = useParams<{ id: string }>();
  return <PublicMapViewer key={id} />;
}

function PublicMapViewer() {
  const { t } = useTranslation('common');
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, isError, error } = useMap(id);
  useDocumentTitle(data?.name ?? t('common:pageTitle.map'));

  const layers = useMemo(
    () => (data?.layers ?? []).map(toSharedLayer),
    [data?.layers],
  );

  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(layers, { mapKey: id });

  const [basemapId, setBasemapId] = useState<string | null>(null);
  const [drawnLayers, setDrawnLayers] = useState<ReadonlyMap<string, DrawnLayer>>();
  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  const handleLegendToggle = useCallback(() => setIsLegendOpen((prev) => !prev), [setIsLegendOpen]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center w-full bg-muted">
        <LoadingState message={t('viewer.loading')} />
      </div>
    );
  }

  if (isError || !data) {
    return <MapUnavailableState error={error} mapId={id} />;
  }

  const viewState = {
    center_lng: data.center_lng ?? 0,
    center_lat: data.center_lat ?? 0,
    zoom: data.zoom ?? 2,
    bearing: data.bearing,
    pitch: data.pitch,
  };

  return (
    // Inside AppLayout's <main id="main-content">, so not a second <main>
    // landmark. The id stays: MapErrorBoundary and CSS target #map-viewport.
    <div id="map-viewport" className="w-full flex-1 min-h-0 relative overflow-hidden">
      <MapErrorBoundary className="absolute inset-0">
        <Suspense fallback={<LoadingState message={t('viewer.loading')} />}>
          <ViewerMap
            layers={layers}
            basemapStyle={basemapId ?? data.basemap_style}
            basemapConfig={data.basemap_config ?? null}
            showBasemapLabels={data.show_basemap_labels ?? true}
            terrainConfig={data.terrain_config ?? null}
            initialViewState={viewState}
            visibleLayers={visibleLayers}
            onMapReady={(map) => {
              mapInstanceRef.current = map;
            }}
            onDrawnChange={setDrawnLayers}
          />
        </Suspense>
      </MapErrorBoundary>

      <MapTitlePill name={data.name} description={data.description} />

      <LayerLegend
        layers={layers}
        visibleLayers={visibleLayers}
        onToggleVisibility={handleToggleVisibility}
        isOpen={isLegendOpen}
        onToggle={handleLegendToggle}
        terrainConfig={data.terrain_config ?? null}
        legendTitle={data.legend_title ?? null}
        drawn={drawnLayers}
      />

      <BasemapToggle
        value={basemapId ?? data.basemap_style}
        onChange={setBasemapId}
        title={t('viewer.changeBasemap')}
        className="absolute bottom-8 start-3 z-10"
      />

      {/* Read-only "Ask AI"; self-gates on AI availability + use_ai_chat, so
          anonymous and unpermitted viewers render nothing. */}
      {id && (
        <ViewerChatPanel mapId={id} layers={data.layers} mapInstanceRef={mapInstanceRef} />
      )}
    </div>
  );
}
