import { lazy, memo, Suspense, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from 'react';
import { MapPinOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { toSharedLayer } from '@/components/viewer/shared-layer';
import type { DrawnLayer } from '@/components/map/legend-facts';
import { LoadingState } from '@/components/layout/LoadingState';
import { MapErrorBoundary } from '@/components/error';
import { motionDuration } from '@/lib/reduced-motion';
import { readMapCamera } from '@/components/builder/builder-camera';
import type { StoryCamera } from '@/types/api';
import { applySceneVisibility, cameraViewState, toStoryCamera, type ResolvedScene } from './story-scenes';

// Lazy so the map-vendor chunk loads only once a scene is shown.
const ViewerMap = lazy(() =>
  import('@/components/viewer/ViewerMap').then((m) => ({ default: m.ViewerMap })),
);

const FLY_DURATION_MS = 2000;

export interface StoryMapPaneHandle {
  /** The map's current view as a scene stores it, or null while no map is ready. */
  getView(): StoryCamera | null;
}

interface StoryMapPaneProps {
  resolved: ResolvedScene | null;
  /** Shown in place of the map while no chapter has a scene. */
  emptyHint?: string;
  ref?: Ref<StoryMapPaneHandle>;
}

/** The story's map. A scene on another map remounts it; one on the same map flies there. */
export const StoryMapPane = memo(function StoryMapPane({ resolved, emptyHint, ref }: StoryMapPaneProps) {
  return (
    // Not a landmark: the page's <main> holds it. MapErrorBoundary targets the id.
    <div id="map-viewport" className="absolute inset-0 overflow-hidden bg-muted">
      {resolved ? (
        <StoryMap key={resolved.scene.map_id} resolved={resolved} handleRef={ref} />
      ) : (
        emptyHint && (
          <p className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
            {emptyHint}
          </p>
        )
      )}
    </div>
  );
});

function StoryMap({ resolved, handleRef }: { resolved: ResolvedScene; handleRef?: Ref<StoryMapPaneHandle> }) {
  const { t } = useTranslation('stories');
  const { scene, chapterId } = resolved;
  const { data, isLoading, isError } = useMap(scene.map_id);

  const layers = useMemo(() => (data?.layers ?? []).map(toSharedLayer), [data?.layers]);
  const sceneLayers = useMemo(
    () => applySceneVisibility(layers, scene.layer_visibility),
    [layers, scene.layer_visibility],
  );
  // A reader's legend toggles last until the scene changes: another chapter,
  // or new layer visibility from the editor's checkboxes.
  const visibilityKey = JSON.stringify(scene.layer_visibility ?? {});
  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(sceneLayers, { mapKey: `${chapterId}:${visibilityKey}` });
  const [drawnLayers, setDrawnLayers] = useState<ReadonlyMap<string, DrawnLayer>>();

  const mapRef = useRef<MaplibreMap | null>(null);
  const cameraRef = useRef(scene.camera);
  useEffect(() => {
    cameraRef.current = scene.camera;
  }, [scene.camera]);

  // Keyed on the chapter rather than the camera object, so a background
  // refetch of the story doesn't pull a reader back from where they panned.
  useEffect(() => {
    mapRef.current?.flyTo({ ...cameraRef.current, duration: motionDuration(FLY_DURATION_MS) });
  }, [chapterId]);

  // Unmounting with the map clears the handle, so a remount never reads the old map.
  useImperativeHandle(
    handleRef,
    () => ({ getView: () => (mapRef.current ? toStoryCamera(readMapCamera(mapRef.current)) : null) }),
    [],
  );

  // The reader may have moved on while the map loaded.
  const handleMapReady = useCallback((map: MaplibreMap) => {
    mapRef.current = map;
    map.jumpTo(cameraRef.current);
  }, []);

  // ViewerMap reads its view once, at mount.
  const [initialViewState] = useState(() => cameraViewState(scene.camera));

  if (isLoading) return <LoadingState className="h-full" message={t('reader.mapLoading')} />;

  if (isError || !data) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="flex max-w-xs flex-col items-center gap-2 text-sm text-muted-foreground">
          <MapPinOff className="size-8" aria-hidden="true" />
          {t('reader.mapUnavailable')}
        </p>
      </div>
    );
  }

  return (
    <>
      <MapErrorBoundary className="absolute inset-0">
        <Suspense fallback={<LoadingState message={t('reader.mapLoading')} />}>
          <ViewerMap
            layers={layers}
            basemapStyle={data.basemap_style}
            basemapConfig={data.basemap_config ?? null}
            showBasemapLabels={data.show_basemap_labels ?? true}
            terrainConfig={data.terrain_config ?? null}
            initialViewState={initialViewState}
            visibleLayers={visibleLayers}
            onMapReady={handleMapReady}
            onDrawnChange={setDrawnLayers}
          />
        </Suspense>
      </MapErrorBoundary>
      <LayerLegend
        layers={layers}
        visibleLayers={visibleLayers}
        onToggleVisibility={handleToggleVisibility}
        isOpen={isLegendOpen}
        onToggle={() => setIsLegendOpen((prev) => !prev)}
        terrainConfig={data.terrain_config ?? null}
        legendTitle={data.legend_title ?? null}
        drawn={drawnLayers}
      />
    </>
  );
}
