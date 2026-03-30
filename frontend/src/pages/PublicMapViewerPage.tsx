import { useState, useCallback, useMemo, useEffect } from 'react';
import { useParams } from 'react-router';
import { useMap } from '@/hooks/use-maps';
import { ViewerMap } from '@/components/viewer/ViewerMap';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { MapPinOff } from 'lucide-react';
import { ApiError } from '@/api/client';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/layout/LoadingState';
import { useDocumentTitle } from '@/hooks/use-document-title';
import type { MapLayerResponse, SharedLayerResponse } from '@/types/api';

/**
 * Transform a MapLayerResponse (from GET /maps/{id}) into the SharedLayerResponse
 * format that ViewerMap consumes. The tile_url field is set to a placeholder since
 * ViewerMap builds the actual tile URL from table_name via buildSignedTileUrl.
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
    // ViewerMap builds the actual URL via buildSignedTileUrl(table_name, token)
    tile_url: `/api/tiles/data.${layer.dataset_table_name}/{z}/{x}/{y}.pbf`,
  };
}

export function PublicMapViewerPage() {
  const { t } = useTranslation('common');
  const { id } = useParams<{ id: string }>();
  useDocumentTitle('Map');

  const { data, isLoading, isError, error } = useMap(id);

  const layers = useMemo(
    () => (data?.layers ?? []).map(toSharedLayer),
    [data],
  );

  const [visibleLayers, setVisibleLayers] = useState<Set<number> | null>(null);

  const effectiveVisibleLayers = useMemo(() => {
    if (visibleLayers !== null) return visibleLayers;
    if (!data) return new Set<number>();
    return new Set(data.layers.filter((l) => l.visible).map((l) => l.sort_order));
  }, [visibleLayers, data]);

  const [isLegendOpen, setIsLegendOpen] = useState(() => {
    return typeof window !== 'undefined' ? window.innerWidth >= 500 : true;
  });

  useEffect(() => {
    const handleResize = () => {
      setIsLegendOpen(window.innerWidth >= 500);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleToggleVisibility = useCallback((sortOrder: number) => {
    setVisibleLayers((prev) => {
      const current = prev ?? new Set(
        (data?.layers ?? []).filter((l) => l.visible).map((l) => l.sort_order),
      );
      const next = new Set(current);
      if (next.has(sortOrder)) {
        next.delete(sortOrder);
      } else {
        next.add(sortOrder);
      }
      return next;
    });
  }, [data]);

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
          <h1 className="text-lg font-semibold text-foreground">
            {isNotFound ? t('viewer.mapNotFound') : t('viewer.loadFailed', 'Unable to load map')}
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
    <div className="w-full h-screen relative overflow-hidden">
      <ViewerMap
        layers={layers}
        basemapStyle={data.basemap_style}
        showBasemapLabels={data.show_basemap_labels ?? true}
        initialViewState={viewState}
        visibleLayers={effectiveVisibleLayers}
      />

      {/* Floating title pill */}
      <div className="absolute top-3 left-14 z-10 pointer-events-none">
        <div className="bg-background/80 backdrop-blur-sm rounded-full px-3 py-1 shadow-sm border border-border/50">
          <h1 className="text-sm font-medium text-foreground truncate max-w-[200px]" title={data.name}>
            {data.name}
          </h1>
        </div>
      </div>

      <LayerLegend
        layers={layers}
        visibleLayers={effectiveVisibleLayers}
        onToggleVisibility={handleToggleVisibility}
        isOpen={isLegendOpen}
        onToggle={() => setIsLegendOpen((prev) => !prev)}
      />
    </div>
  );
}
