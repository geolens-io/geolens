import { lazy, memo, Suspense, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from 'react';
import { MapPinOff, Undo2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { LayerLegend } from '@/components/viewer/LayerLegend';
import { toSharedLayer } from '@/components/viewer/shared-layer';
import type { DrawnLayer } from '@/components/map/legend-facts';
import { LoadingState } from '@/components/layout/LoadingState';
import { MapErrorBoundary } from '@/components/error';
import { Button } from '@/components/ui/button';
import { motionDuration } from '@/lib/reduced-motion';
import { readMapCamera } from '@/components/builder/builder-camera';
import type { StoryCamera } from '@/types/api';
import {
  applySceneVisibility,
  cameraDiffers,
  cameraGap,
  cameraViewState,
  panTolerancePx,
  toStoryCamera,
  transitionDuration,
  type ResolvedScene,
} from './story-scenes';

// Lazy so the map-vendor chunk loads only once a scene is shown.
const ViewerMap = lazy(() =>
  import('@/components/viewer/ViewerMap').then((m) => ({ default: m.ViewerMap })),
);

export interface StoryMapPaneHandle {
  /** The map's current view as a scene stores it, or null while no map is ready. */
  getView(): StoryCamera | null;
}

interface StoryMapPaneProps {
  resolved: ResolvedScene | null;
  /** Shown in place of the map while no chapter has a scene. */
  emptyHint?: string;
  /**
   * Changes when the scenes were replaced on purpose (the editor's discard or
   * reload), so the map moves back to the scene's camera even on the same
   * chapter and map.
   */
  resetKey?: number;
  /** The edge the legend sits on, so a floating chapter panel never covers it. */
  legendSide?: 'start' | 'end';
  ref?: Ref<StoryMapPaneHandle>;
}

/** The story's map. A scene on another map remounts it; one on the same map flies there. */
export const StoryMapPane = memo(function StoryMapPane({ resolved, emptyHint, resetKey, legendSide, ref }: StoryMapPaneProps) {
  return (
    // Not a landmark: the page's <main> holds it. MapErrorBoundary targets the id.
    <div id="map-viewport" className="absolute inset-0 overflow-hidden bg-muted">
      {resolved ? (
        <StoryMap key={resolved.scene.map_id} resolved={resolved} resetKey={resetKey} legendSide={legendSide} handleRef={ref} />
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

function StoryMap({
  resolved,
  resetKey,
  legendSide,
  handleRef,
}: {
  resolved: ResolvedScene;
  resetKey?: number;
  legendSide?: 'start' | 'end';
  handleRef?: Ref<StoryMapPaneHandle>;
}) {
  const { t } = useTranslation('stories');
  const { scene, chapterId } = resolved;
  const { data, isLoading, isError } = useMap(scene.map_id);
  // Counts the times the map is sent back to the scene's camera: the editor's
  // reset key and the reader's return button.
  const [returns, setReturns] = useState(0);
  const sceneVisit = (resetKey ?? 0) + returns;

  const layers = useMemo(() => (data?.layers ?? []).map(toSharedLayer), [data?.layers]);
  const sceneLayers = useMemo(
    () => applySceneVisibility(layers, scene.layer_visibility),
    [layers, scene.layer_visibility],
  );
  // A reader's legend toggles last until the scene changes: another chapter,
  // or new layer visibility from the editor's checkboxes.
  const visibilityKey = JSON.stringify(scene.layer_visibility ?? {});
  const { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen } =
    useViewerLayers(sceneLayers, { mapKey: `${chapterId}:${visibilityKey}:${sceneVisit}` });
  const [drawnLayers, setDrawnLayers] = useState<ReadonlyMap<string, DrawnLayer>>();

  const mapRef = useRef<MaplibreMap | null>(null);
  const sceneRef = useRef(scene);
  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);

  const [away, setAway] = useState(false);
  // Our own moves not yet ended by a moveend, so one that ends them isn't taken for the reader's.
  const inFlight = useRef(0);
  const tolerance = useRef(0);
  const checkAway = useCallback((map: MaplibreMap) => {
    setAway(cameraDiffers(map, sceneRef.current.camera, tolerance.current));
  }, []);

  // Cut is a zero-length move, as is every move under reduced motion.
  const playTransition = useCallback((map: MaplibreMap) => {
    const { camera, transition } = sceneRef.current;
    const duration = transition === 'cut' ? 0 : motionDuration(transitionDuration(cameraGap(map, camera)));
    const options = { ...camera, duration };
    // Before the call: starting a move first ends the one running, and a zero-length move ends inside the call.
    inFlight.current += 1;
    if (transition === 'glide' || transition === 'cut') map.easeTo(options);
    else map.flyTo(options);
    setAway(false);
  }, []);

  // A new camera for the chapter on screen, such as "Use current view" saves, is compared at once. A chapter change plays its own move instead.
  const shownChapter = useRef(chapterId);
  useEffect(() => {
    const sameChapter = shownChapter.current === chapterId;
    shownChapter.current = chapterId;
    // A move in flight ends with its own comparison against this camera.
    if (sameChapter && mapRef.current && inFlight.current === 0) checkAway(mapRef.current);
  }, [scene.camera, chapterId, checkAway]);

  // Keyed on the chapter and the scene visit rather than the camera object, so a
  // background refetch of the story doesn't pull a reader back from where they panned.
  useEffect(() => {
    if (mapRef.current) playTransition(mapRef.current);
  }, [chapterId, sceneVisit, playTransition]);

  // Unmounting with the map clears the handle, so a remount never reads the old map.
  useImperativeHandle(
    handleRef,
    () => ({ getView: () => (mapRef.current ? toStoryCamera(readMapCamera(mapRef.current)) : null) }),
    [],
  );

  // The reader may have moved on while the map loaded.
  const [readyMap, setReadyMap] = useState<MaplibreMap | null>(null);
  const handleMapReady = useCallback((map: MaplibreMap) => {
    mapRef.current = map;
    setReadyMap(map);
    map.jumpTo(sceneRef.current.camera);
  }, []);

  // MapLibre marks a reader's drag, wheel, touch, keys and buttons with an originalEvent; the compass sets none.
  useEffect(() => {
    if (!readyMap) return;
    tolerance.current = panTolerancePx(readyMap);
    inFlight.current = 0;
    const onResize = () => {
      tolerance.current = panTolerancePx(readyMap);
    };
    const onMoveEnd = (event: { originalEvent?: unknown }) => {
      if (!event.originalEvent && inFlight.current > 0) {
        inFlight.current -= 1;
        // A flight stopped by a press or tap leaves the map between views, with no move after it.
        if (inFlight.current > 0) return;
      }
      checkAway(readyMap);
    };
    readyMap.on('resize', onResize);
    readyMap.on('moveend', onMoveEnd);
    return () => {
      readyMap.off('resize', onResize);
      readyMap.off('moveend', onMoveEnd);
    };
  }, [readyMap, checkAway]);

  const returnToChapterView = () => {
    const map = mapRef.current;
    if (!map) return;
    setReturns((n) => n + 1);
    // The button leaves with the click, so focus goes to the map rather than the page.
    map.getCanvas().focus();
  };

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
          {/* The scene's layers, so saved-visibility checks (terrain from a
              DEM the map saved as hidden) follow the scene too. */}
          <ViewerMap
            layers={sceneLayers}
            basemapStyle={data.basemap_style}
            basemapConfig={data.basemap_config ?? null}
            showBasemapLabels={data.show_basemap_labels ?? true}
            terrainConfig={data.terrain_config ?? null}
            initialViewState={initialViewState}
            visibleLayers={visibleLayers}
            onMapReady={handleMapReady}
            onDrawnChange={setDrawnLayers}
            showAttributeTable={data.show_attribute_table}
            fadeLayerChanges
          />
        </Suspense>
      </MapErrorBoundary>
      {away && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="absolute left-1/2 top-3 z-10 -translate-x-1/2 shadow-md"
          onClick={returnToChapterView}
        >
          <Undo2 className="h-4 w-4" aria-hidden="true" />
          {t('reader.backToChapterView')}
        </Button>
      )}
      <LayerLegend
        layers={sceneLayers}
        visibleLayers={visibleLayers}
        onToggleVisibility={handleToggleVisibility}
        isOpen={isLegendOpen}
        onToggle={() => setIsLegendOpen((prev) => !prev)}
        terrainConfig={data.terrain_config ?? null}
        legendTitle={data.legend_title ?? null}
        drawn={drawnLayers}
        side={legendSide}
      />
    </>
  );
}
