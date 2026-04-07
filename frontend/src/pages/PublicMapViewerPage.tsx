import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/hooks/use-viewer-layers';
import { ViewerMap } from '@/components/viewer/ViewerMap';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { MapTitlePill } from '@/components/map/MapTitlePill';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { MapPinOff } from 'lucide-react';
import { ApiError } from '@/api/client';
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
    label_config: layer.label_config,
    style_config: layer.style_config,
    show_in_legend: layer.show_in_legend,
    tile_url: `/api/tiles/data.${layer.dataset_table_name}/{z}/{x}/{y}.pbf`,
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
  const handleLegendToggle = useCallback(() => setIsLegendOpen((prev) => !prev), [setIsLegendOpen]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center w-full h-screen bg-muted">
        <LoadingState message={t('viewer.loading')} />
      </div>
    );
  }

  if (isError || !data) {
    const isNotFound = error instanceof ApiError && (error.status === 404 || error.status === 403);
    return (
      <div className="flex items-center justify-center w-full h-screen bg-muted">
        <div className="flex flex-col items-center gap-3 text-center">
          <MapPinOff className="size-10 text-muted-foreground" />
          <h1 className="text-2xl font-semibold text-foreground">
            {isNotFound ? t('viewer.mapNotFound') : t('viewer.loadFailed')}
          </h1>
          <p className="text-sm text-muted-foreground max-w-sm">
            {t('viewer.mapNotFoundDescription')}
          </p>
        </div>
      </div>
    );
  }

  const viewState = {
    center_lng: data.center_lng ?? 0,
    center_lat: data.center_lat ?? 0,
    zoom: data.zoom ?? 2,
    bearing: data.bearing,
    pitch: data.pitch,
  };

  return (
    <main id="map-viewport" className="w-full h-[calc(100dvh-3.5rem-1px)] relative overflow-hidden">
      <MapErrorBoundary>
        <ViewerMap
          layers={layers}
          basemapStyle={basemapId ?? data.basemap_style}
          basemapOverride={basemapId !== null}
          showBasemapLabels={data.show_basemap_labels ?? true}
          initialViewState={viewState}
          visibleLayers={visibleLayers}
        />
      </MapErrorBoundary>

      <MapTitlePill name={data.name} description={data.description} />

      <LayerLegend
        layers={layers}
        visibleLayers={visibleLayers}
        onToggleVisibility={handleToggleVisibility}
        isOpen={isLegendOpen}
        onToggle={handleLegendToggle}
      />

      <BasemapToggle
        value={basemapId ?? data.basemap_style}
        onChange={setBasemapId}
        title={t('viewer.changeBasemap')}
        className="absolute bottom-8 left-3 z-10"
      />
    </main>
  );
}
