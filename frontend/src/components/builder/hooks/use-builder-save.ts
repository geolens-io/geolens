import { useCallback, useEffect, useRef } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getSourceId } from '@/components/builder/map-sync';
import { useUpdateMap, useDuplicateMap } from '@/hooks/use-maps';
import { uploadThumbnail } from '@/api/maps';
import type { MapLayerResponse, MapResponse } from '@/types/api';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';

/** Crop and resize the map canvas to a 400x250 JPEG, then upload it. */
function doCapture(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
  try {
    const srcCanvas = map.getCanvas();
    const thumbW = 400;
    const thumbH = 250;
    const targetRatio = thumbW / thumbH;
    const srcW = srcCanvas.width;
    const srcH = srcCanvas.height;
    const srcRatio = srcW / srcH;

    let cropX = 0, cropY = 0, cropW = srcW, cropH = srcH;
    if (srcRatio > targetRatio) {
      cropW = Math.round(srcH * targetRatio);
      cropX = Math.round((srcW - cropW) / 2);
    } else {
      cropH = Math.round(srcW / targetRatio);
      cropY = Math.round((srcH - cropH) / 2);
    }

    const offscreen = document.createElement('canvas');
    offscreen.width = thumbW;
    offscreen.height = thumbH;
    const ctx = offscreen.getContext('2d');
    if (ctx) {
      ctx.drawImage(srcCanvas, cropX, cropY, cropW, cropH, 0, 0, thumbW, thumbH);
      const dataUri = offscreen.toDataURL('image/jpeg', 0.7);
      uploadThumbnail(mapId, dataUri).then(() => {
        queryClient.invalidateQueries({ queryKey: queryKeys.maps.all });
      }).catch(() => {
        // Silent failure for thumbnails
      });
    }
  } catch (err) {
    if (import.meta.env.DEV) console.warn('[thumbnail] capture failed:', err);
  }
}

/** Run `fn` immediately if the map is loaded, otherwise wait for the idle event
 *  with a 3-second safety timeout to prevent silent drops. */
function whenMapIdle(map: MaplibreMap, fn: () => void) {
  if (map.loaded()) { fn(); return; }
  let done = false;
  const onIdle = () => { if (done) return; done = true; clearTimeout(timer); fn(); };
  map.once('idle', onIdle);
  const timer = setTimeout(() => { if (!done) { done = true; map.off('idle', onIdle); fn(); } }, 3000);
}

function waitForVisibleLayerSources(
  map: MaplibreMap,
  layers: MapLayerResponse[],
  fn: () => void,
  signal?: { cancelled: boolean },
) {
  const visibleSourceIds = layers
    .filter((layer) => layer.visible)
    .map((layer) => getSourceId(layer.id));

  if (visibleSourceIds.length === 0) {
    whenMapIdle(map, fn);
    return;
  }

  const deadline = Date.now() + 5000;

  const poll = () => {
    if (signal?.cancelled) return;
    const sourcesReady = visibleSourceIds.every((sourceId) => !!map.getSource(sourceId));
    if (sourcesReady || Date.now() >= deadline) {
      if (!signal?.cancelled) whenMapIdle(map, fn);
      return;
    }
    setTimeout(poll, 100);
  };

  poll();
}

/** Capture a 400x250 JPEG thumbnail from the map canvas and upload it.
 *  If the map is already idle/loaded, captures immediately (preserveDrawingBuffer
 *  guarantees canvas contents persist). Otherwise waits for the idle event with a
 *  3-second safety timeout to prevent silent drops. */
function captureThumbnail(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
) {
  // Auto-capture can run before BuilderMap has synced GeoLens sources. Wait
  // for visible sources first so the thumbnail includes rendered layers.
  waitForVisibleLayerSources(map, layers, () => doCapture(map, mapId, queryClient), signal);
}

function resolveWidgetsPayload(
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
): string[] | undefined {
  const active = Array.from(useWidgetStore.getState().activeWidgets);
  const cached = queryClient.getQueryData<MapResponse>(queryKeys.maps.detail(mapId));
  if (cached?.widgets == null && active.length === 0) return undefined;
  return active;
}

interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  showBasemapLabels: boolean;
  localName: string;
  localDescription: string;
  dockNotes: string;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
  hasThumbnail?: boolean;
}

export function useBuilderSave(state: SaveState) {
  const { t } = useTranslation('builder');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const updateMap = useUpdateMap();
  const duplicateMutation = useDuplicateMap();

  function handleSave() {
    const { mapId: id, mapInstanceRef, localName, localDescription, dockNotes, localBasemap, localLayers, showBasemapLabels } = state;
    if (!id) return;
    const map = mapInstanceRef.current;
    const center = map?.getCenter();
    const zoom = map?.getZoom();
    const bearing = map?.getBearing();
    const pitch = map?.getPitch();

    updateMap.mutate(
      {
        id,
        data: {
          name: localName || undefined,
          description: localDescription.trim() || null,
          notes: dockNotes.trim() || null,
          basemap_style: localBasemap,
          show_basemap_labels: showBasemapLabels,
          center_lng: center?.lng ?? null,
          center_lat: center?.lat ?? null,
          zoom: zoom ?? null,
          bearing: bearing ?? 0,
          pitch: pitch ?? 0,
          widgets: resolveWidgetsPayload(id, queryClient),
          layers: localLayers.map((l) => ({
            dataset_id: l.dataset_id,
            sort_order: l.sort_order,
            visible: l.visible,
            opacity: l.opacity,
            paint: l.paint,
            layout: l.layout,
            display_name: l.display_name ?? null,
            filter: l.filter ?? null,
            label_config: l.label_config ?? null,
            style_config: l.style_config ?? null,
            layer_type: l.layer_type ?? null,
            show_in_legend: l.show_in_legend ?? true,
          })),
        },
      },
      {
        onSuccess: () => {
          toast.success(t('toasts.mapSaved'));
          state.setHasUnsavedChanges(false);

          // Capture thumbnail and upload (fire-and-forget)
          // Use `map` captured before mutate — mapInstanceRef.current may be
          // transiently null during re-render (callback ref identity change).
          if (map && id) {
            captureThumbnail(map, id, queryClient, localLayers);
          }
        },
        onError: () => {
          toast.error(t('toasts.saveFailed'));
        },
      },
    );
  }

  function handleExportPNG() {
    const map = state.mapInstanceRef.current;
    if (!map) return;

    const doExport = () => {
      try {
        const canvas = map.getCanvas();
        canvas.toBlob((blob) => {
          if (!blob) {
            toast.error(t('toasts.exportFailed'));
            return;
          }
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${state.localName || 'map'}-export.png`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          toast.success(t('toasts.exportSuccess'));
        }, 'image/png');
      } catch {
        toast.error(t('toasts.exportFailed'));
      }
    };

    whenMapIdle(map, doExport);
  }

  async function handleFork() {
    if (!state.mapId) return;
    try {
      const result = await duplicateMutation.mutateAsync(state.mapId);
      if (result.excluded_layer_count > 0) {
        toast.warning(
          t('toasts.mapForkedExcluded', { count: result.excluded_layer_count }),
        );
      } else {
        toast.success(t('toasts.mapDuplicated'));
      }
      navigate(`/maps/${result.id}`);
    } catch {
      toast.error(t('toasts.mapDuplicateFailed'));
    }
  }

  // Auto-capture thumbnail on first map load if none exists.
  // Called from handleMapRef when the map instance becomes available.
  // Memoized to stabilize the callback ref identity in MapBuilderPage,
  // preventing transient null ref cycles during re-renders.
  const thumbCaptured = useRef(false);
  const captureSignalRef = useRef<{ cancelled: boolean }>({ cancelled: false });
  const localLayersRef = useRef(state.localLayers);
  localLayersRef.current = state.localLayers;

  const maybeAutoCaptureThumbnail = useCallback((map: MaplibreMap) => {
    if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
    thumbCaptured.current = true;
    captureSignalRef.current = { cancelled: false };
    captureThumbnail(map, state.mapId, queryClient, localLayersRef.current, captureSignalRef.current);
  }, [state.hasThumbnail, state.mapId, queryClient]);

  // P-08: Cancel in-flight polling on unmount
  useEffect(() => {
    return () => { captureSignalRef.current.cancelled = true; };
  }, []);

  // Warn before tab close / refresh with unsaved changes, and block in-app navigation
  const blocker = useUnsavedGuard(state.hasUnsavedChanges);

  // Keyboard shortcut: Ctrl/Cmd+S
  const handleSaveRef = useRef(handleSave);
  handleSaveRef.current = handleSave;
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (!updateMap.isPending) handleSaveRef.current();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return {
    handleSave,
    handleExportPNG,
    handleFork,
    maybeAutoCaptureThumbnail,
    isSaving: updateMap.isPending,
    isForkPending: duplicateMutation.isPending,
    blocker,
  };
}
