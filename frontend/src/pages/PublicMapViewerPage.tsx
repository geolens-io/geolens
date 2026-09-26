import { lazy, Suspense, useCallback, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
// PERF-06 (Phase 274): lazy-load ViewerMap so map-vendor chunk fetch
// is deferred until the share-token resolves and rendering is imminent.
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
import type { MapLayerResponse, SharedLayerResponse } from '@/types/api';

/**
 * Transform a MapLayerResponse (from GET /maps/{id}) into the SharedLayerResponse
 * format that ViewerMap consumes.
 */
function toSharedLayer(layer: MapLayerResponse): SharedLayerResponse {
  return {
    id: layer.id,
    dataset_id: layer.dataset_id,
    dataset_name: layer.dataset_name,
    display_name: layer.display_name,
    table_name: layer.dataset_table_name,
    geometry_type: layer.dataset_geometry_type,
    column_info: layer.dataset_column_info,
    sort_order: layer.sort_order,
    visible: layer.visible,
    opacity: layer.opacity,
    paint: layer.paint,
    layout: layer.layout,
    filter: layer.filter,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ?? null,
    show_in_legend: layer.show_in_legend,
    layer_type: layer.layer_type ?? undefined,
    dataset_record_type: layer.dataset_record_type ?? undefined,
    is_dem: layer.is_dem ?? undefined,
    dem_vertical_units: layer.dem_vertical_units ?? null,
    is_3d: layer.is_3d ?? null,
    feature_count: layer.dataset_feature_count ?? null,
    // fix(#403): without the version stamp the anonymous viewer builds tile
    // URLs with no _v= cache-buster, so in-place dataset refreshes (e.g.
    // seed-showcase.py --refresh-quakes) keep serving stale tiles from cache.
    tile_version: layer.tile_version ?? null,
    // feat(#1472): this adapter drops anything it does not list, so the credit
    // line has to be copied explicitly or /maps/{id} renders no attribution
    // while the share link for the same map does.
    dataset_attribution: layer.dataset_attribution ?? null,
    tile_url: '',
  };
}

export function PublicMapViewerPage() {
  const { t } = useTranslation('common');
  const { id } = useParams<{ id: string }>();
  useDocumentTitle(t('common:pageTitle.map'));

  const { data, isLoading, isError, error } = useMap(id);

  const layers = useMemo(
    () => (data?.layers ?? []).map(toSharedLayer),
    [data?.layers],
  );

  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(layers);

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
    // This page renders inside AppLayout's <main id="main-content">, so it must
    // not be a second <main> landmark. The id stays: MapErrorBoundary and CSS
    // target #map-viewport, and the skip link keeps targeting #main-content.
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

      {/* Read-only "Ask AI" — self-gates on AI availability + use_ai_chat, so anonymous
          and unpermitted viewers render nothing (PR #339 follow-up). */}
      {id && (
        <ViewerChatPanel mapId={id} layers={data.layers} mapInstanceRef={mapInstanceRef} />
      )}
    </div>
  );
}
