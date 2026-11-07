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
import { cn } from '@/lib/utils';
import { motionDuration } from '@/lib/reduced-motion';
import { readMapCamera } from '@/components/builder/builder-camera';
import type { StoryCamera, StoryScene, StorySettings } from '@/types/api';
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

/** How long the next map takes to fade in over the current one. */
const CROSSFADE_MS = 400;
const COVER_MAX_MS = 4000;
// Centres the button in the map the floating panel leaves free (panel widths
// and offsets match StoryReader's FLOATING_PLACEMENT), one row below the
// coordinate readout, which shares that strip at narrow desktop widths.
const BACK_BUTTON_PLACEMENT = {
  left: 'top-10 left-[calc((100%+3.5rem+26rem)/2)] lg:left-[calc((100%+3.5rem+30rem)/2)]',
  right: 'top-10 left-[calc((100%-3.5rem-26rem)/2)] lg:left-[calc((100%-3.5rem-30rem)/2)]',
  center: 'top-10 left-[calc((100%-3.5rem-26rem)/2)] lg:left-[calc((50%-15rem)/2)]',
};

export interface StoryMapPaneHandle {
  /** The map's current view as a scene stores it, or null while no map is ready. */
  getView(): StoryCamera | null;
}

interface StoryMapPaneProps {
  resolved: ResolvedScene | null;
  /** The next scene on another map, loaded hidden behind the current map so the change can crossfade. */
  next?: ResolvedScene | null;
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
  /** Where a floating chapter panel sits, so the map's own controls stay out from under it. */
  panel?: 'left' | 'right' | 'center';
  /** The story's transition for a scene that sets none. */
  defaultTransition?: StorySettings['transition'];
  ref?: Ref<StoryMapPaneHandle>;
}

/**
 * The story's map. A scene on another map crossfades from a copy loaded
 * ahead; without one ready, the map remounts. A scene on the same map flies there.
 */
export const StoryMapPane = memo(function StoryMapPane({ resolved, next, emptyHint, resetKey, legendSide, panel, defaultTransition, ref }: StoryMapPaneProps) {
  const [shown, setShown] = useState(resolved);
  // The map that just lost the view, kept underneath while the next one fades in.
  const [outgoing, setOutgoing] = useState<ResolvedScene | null>(null);
  const [standby, setStandby] = useState<ResolvedScene | null>(null);
  const [standbyReady, setStandbyReady] = useState(false);

  // Settled in render so the old map never unmounts a frame before the new one shows.
  if (shown !== resolved) {
    setShown(resolved);
    if (shown?.scene.map_id !== resolved?.scene.map_id) {
      const crossfade =
        !!shown && standbyReady && !!standby && standby.scene.map_id === resolved?.scene.map_id && motionDuration(CROSSFADE_MS) > 0;
      setOutgoing(crossfade ? shown : null);
    }
  }
  // At most two maps: the next one loads only once the fade has ended.
  const wanted = !outgoing && resolved && next && next.scene.map_id !== resolved.scene.map_id ? next : null;
  if (
    standby?.scene.map_id !== wanted?.scene.map_id ||
    standby?.chapterId !== wanted?.chapterId ||
    JSON.stringify(standby?.scene) !== JSON.stringify(wanted?.scene)
  ) {
    setStandby(wanted);
  }

  useEffect(() => {
    if (!outgoing) return;
    const timer = setTimeout(() => setOutgoing(null), CROSSFADE_MS + 100);
    return () => clearTimeout(timer);
  }, [outgoing]);

  const slots: { scene: ResolvedScene; role: SlotRole }[] = [];
  if (outgoing) slots.push({ scene: outgoing, role: 'outgoing' });
  if (standby) slots.push({ scene: standby, role: 'standby' });
  if (resolved) slots.push({ scene: resolved, role: 'active' });
  // Slots keep the order they mounted in: a node that React moves loses its
  // computed style, and the fade-in would jump. Stacking is by z-index.
  const mountOrder = useRef<string[]>([]);
  for (const { scene } of slots) if (!mountOrder.current.includes(scene.scene.map_id)) mountOrder.current.push(scene.scene.map_id);
  const liveIds = slots.map((slot) => slot.scene.scene.map_id).join('|');
  // Pruned after commit: a render that React discards must not forget a slot.
  useEffect(() => {
    const live = liveIds.split('|');
    mountOrder.current = mountOrder.current.filter((id) => live.includes(id));
  }, [liveIds]);
  slots.sort((x, y) => mountOrder.current.indexOf(x.scene.scene.map_id) - mountOrder.current.indexOf(y.scene.scene.map_id));

  return (
    // Not a landmark: the page's <main> holds it. MapErrorBoundary targets the id.
    <div id="map-viewport" className="absolute inset-0 isolate overflow-hidden bg-muted">
      {slots.map(({ scene, role }) => (
        <div
          key={scene.scene.map_id}
          data-slot={role}
          inert={role !== 'active'}
          aria-hidden={role !== 'active' || undefined}
          className={cn('absolute inset-0', role === 'active' ? 'z-10' : 'z-0 pointer-events-none')}
          style={{
            opacity: role === 'standby' ? 0 : 1,
            transitionProperty: 'opacity',
            transitionDuration: `${motionDuration(CROSSFADE_MS)}ms`,
          }}
          onTransitionEnd={(event) => {
            if (role === 'active' && event.target === event.currentTarget) setOutgoing(null);
          }}
        >
          <StoryMap
            resolved={scene}
            role={role}
            exit={role === 'outgoing' ? resolved : null}
            onReady={role === 'standby' ? setStandbyReady : undefined}
            resetKey={resetKey}
            legendSide={legendSide}
            panel={panel}
            defaultTransition={defaultTransition}
            handleRef={role === 'active' ? ref : undefined}
          />
        </div>
      ))}
      {!resolved && emptyHint && (
        <p className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
          {emptyHint}
        </p>
      )}
    </div>
  );
});

type SlotRole = 'active' | 'standby' | 'outgoing';

function StoryMap({
  resolved,
  role,
  exit,
  onReady,
  resetKey,
  legendSide,
  panel,
  defaultTransition,
  handleRef,
}: {
  resolved: ResolvedScene;
  role: SlotRole;
  /** The scene an outgoing map moves toward while the next map fades in. */
  exit: ResolvedScene | null;
  onReady?: (ready: boolean) => void;
  resetKey?: number;
  legendSide?: 'start' | 'end';
  panel?: 'left' | 'right' | 'center';
  defaultTransition?: StorySettings['transition'];
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

  const defaultRef = useRef(defaultTransition);
  useEffect(() => {
    defaultRef.current = defaultTransition;
  }, [defaultTransition]);

  const [away, setAway] = useState(false);
  // Our own moves not yet ended by a moveend, so one that ends them isn't taken for the reader's.
  const inFlight = useRef(0);
  const tolerance = useRef(0);
  const checkAway = useCallback((map: MaplibreMap) => {
    setAway(cameraDiffers(map, sceneRef.current.camera, tolerance.current));
  }, []);

  // Cut is a zero-length move, as is every move under reduced motion.
  const playTransition = useCallback((map: MaplibreMap, target: StoryScene = sceneRef.current) => {
    const { camera } = target;
    const transition = target.transition ?? defaultRef.current ?? 'fly';
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

  // A map back on screen after another map had the view starts a new scene visit: authored camera and visibility.
  const prevRole = useRef(role);
  const shownBefore = useRef(role !== 'standby');
  useEffect(() => {
    if (role === 'active' && prevRole.current !== 'active' && shownBefore.current) setReturns((n) => n + 1);
    prevRole.current = role;
    if (role !== 'standby') shownBefore.current = true;
  }, [role]);

  // The outgoing map moves to the view the next map fades in at; a cut holds it still.
  const exitRef = useRef(exit);
  useEffect(() => {
    exitRef.current = exit;
  }, [exit]);
  useEffect(() => {
    const map = mapRef.current;
    if (role !== 'outgoing' || !map || !exitRef.current) return;
    if ((exitRef.current.scene.transition ?? defaultRef.current ?? 'fly') === 'cut') map.stop();
    else playTransition(map, exitRef.current.scene);
  }, [role, playTransition]);

  // Unmounting with the map clears the handle, so a remount never reads the old map.
  useImperativeHandle(
    handleRef,
    () => ({ getView: () => (mapRef.current ? toStoryCamera(readMapCamera(mapRef.current)) : null) }),
    [],
  );

  // The reader may have moved on while the map loaded.
  const [readyMap, setReadyMap] = useState<MaplibreMap | null>(null);
  // Live readiness; the cover latches off once the map has been shown ready or has waited.
  const [viewerReady, setViewerReady] = useState(false);
  const [coverDone, setCoverDone] = useState(false);
  const handleMapReady = useCallback((map: MaplibreMap) => {
    mapRef.current = map;
    setReadyMap(map);
    map.jumpTo(sceneRef.current.camera);
  }, []);

  // A map loaded ahead that is shown before it is ready covers itself with the loading state.
  const loadedAhead = useRef(role === 'standby').current;
  useEffect(() => {
    onReady?.(viewerReady);
  }, [viewerReady, onReady]);

  // The viewer's own entry veil gives up after 4 s; the cover does the same.
  useEffect(() => {
    if (role !== 'active') return;
    if (viewerReady) {
      setCoverDone(true);
      return;
    }
    const timer = setTimeout(() => setCoverDone(true), COVER_MAX_MS);
    return () => clearTimeout(timer);
  }, [role, viewerReady]);

  // A refetch can change the camera of the chapter waiting hidden.
  useEffect(() => {
    if (role === 'standby' && mapRef.current) mapRef.current.jumpTo(scene.camera);
  }, [role, scene.camera]);

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
            onReadyChange={setViewerReady}
            onDrawnChange={setDrawnLayers}
            showAttributeTable={data.show_attribute_table}
            fadeLayerChanges
            coordReadoutSide={panel === 'right' || panel === 'center' ? 'start' : panel === 'left' ? 'past-legend' : undefined}
          />
        </Suspense>
        {loadedAhead && role === 'active' && !coverDone && !viewerReady && (
          <div className="absolute inset-0 z-20 bg-muted">
            <LoadingState className="h-full" message={t('reader.mapLoading')} />
          </div>
        )}
      </MapErrorBoundary>
      {away && role === 'active' && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className={cn('absolute z-10 -translate-x-1/2 shadow-md', panel ? BACK_BUTTON_PLACEMENT[panel] : 'top-3 left-1/2')}
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
