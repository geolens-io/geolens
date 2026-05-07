import { useCallback, useEffect, useMemo, useRef } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getSourceId } from '@/components/builder/map-sync';
import { ApiError } from '@/api/client';
import { useUpdateMap, useDuplicateMap, usePatchMapLayers } from '@/hooks/use-maps';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { uploadThumbnail } from '@/api/maps';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { MapLayerDiffRequest, MapLayerInput, MapLayerPatch, MapLayerResponse, MapResponse, MapTerrainConfig, MapUpdateRequest } from '@/types/api';
import { useWidgetStore } from '@/stores/map-widget-store';
import { getDefaultWidgetIds, resolveAvailableWidgetIds, sameWidgetIds } from '@/components/map-widgets';

/** Crop and resize the map canvas to a 400x250 JPEG, then upload it.
 *  PERF-08 (Phase 274): we no longer keep preserveDrawingBuffer permanently
 *  enabled. Force one render frame and read pixels from the freshly-painted
 *  canvas. Using `once('render')` is more reliable than relying on the
 *  synchronous post-triggerRepaint state because some browsers async-defer
 *  the repaint to the next animation frame. */
function doCapture(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
  const onRender = () => {
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
  };

  map.once('render', onRender);
  map.triggerRepaint();
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
 *  PERF-08 (Phase 274): no longer relies on permanent preserveDrawingBuffer.
 *  Uses map.triggerRepaint() + map.once('render') to read pixels from a
 *  freshly-painted canvas (see doCapture body). If the map is not yet
 *  idle/loaded, waits for idle first via waitForVisibleLayerSources. */
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
  enabledWidgetIds: string[] | null | undefined,
): string[] | null | undefined {
  const active = resolveAvailableWidgetIds(
    useWidgetStore.getState().activeWidgets,
    enabledWidgetIds,
  );
  const cached = queryClient.getQueryData<MapResponse>(queryKeys.maps.detail(mapId));
  if (sameWidgetIds(active, getDefaultWidgetIds(enabledWidgetIds))) {
    return cached?.widgets == null ? undefined : null;
  }
  return active;
}

const PATCHABLE_LAYER_FIELDS = [
  'sort_order',
  'visible',
  'opacity',
  'paint',
  'layout',
  'display_name',
  'filter',
  'label_config',
  'popup_config',
  'style_config',
  'layer_type',
  'show_in_legend',
] as const;

type PatchableLayerField = (typeof PATCHABLE_LAYER_FIELDS)[number];
type LayerSnapshot = Pick<MapLayerResponse, PatchableLayerField | 'id' | 'dataset_id'>;

function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
    return Object.keys(item as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = (item as Record<string, unknown>)[key];
        return acc;
      }, {});
  });
}

function toLayerInput(layer: MapLayerResponse): MapLayerInput {
  return {
    dataset_id: layer.dataset_id,
    sort_order: layer.sort_order,
    visible: layer.visible,
    opacity: layer.opacity,
    paint: layer.paint,
    layout: layer.layout,
    display_name: layer.display_name ?? null,
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ?? null,
    layer_type: layer.layer_type ?? null,
    show_in_legend: layer.show_in_legend ?? true,
  };
}

function toLayerSnapshot(layer: MapLayerResponse): LayerSnapshot {
  return {
    id: layer.id,
    dataset_id: layer.dataset_id,
    sort_order: layer.sort_order,
    visible: layer.visible,
    opacity: layer.opacity,
    paint: layer.paint,
    layout: layer.layout,
    display_name: layer.display_name ?? null,
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ?? null,
    layer_type: layer.layer_type ?? null,
    show_in_legend: layer.show_in_legend ?? true,
  };
}

function hasDiff(diff: MapLayerDiffRequest): boolean {
  return Boolean(
    diff.added?.length ||
    diff.updated?.length ||
    diff.removed?.length ||
    diff.order,
  );
}

function isUnsupportedLayerPatchError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (![400, 404, 409, 422].includes(error.status)) return false;
  const detail = typeof error.body === 'string' ? error.body : error.message;
  return /layer|order|unknown|removed|unsupported|validation/i.test(detail);
}

export interface LayerDiffResult {
  diff: MapLayerDiffRequest;
  unsupported: boolean;
}

export function buildLayerDiff(
  baselineLayers: MapLayerResponse[],
  currentLayers: MapLayerResponse[],
): LayerDiffResult {
  const baselineById = new Map(baselineLayers.map((layer) => [layer.id, toLayerSnapshot(layer)]));
  const currentById = new Map(currentLayers.map((layer) => [layer.id, layer]));

  const added = currentLayers
    .filter((layer) => !baselineById.has(layer.id))
    .map(toLayerInput);
  const removed = baselineLayers
    .filter((layer) => !currentById.has(layer.id))
    .map((layer) => layer.id);
  const updated: MapLayerPatch[] = [];

  for (const layer of currentLayers) {
    const baseline = baselineById.get(layer.id);
    if (!baseline) continue;

    const patch: MapLayerPatch = { id: layer.id };
    for (const field of PATCHABLE_LAYER_FIELDS) {
      const currentValue = toLayerSnapshot(layer)[field];
      const baselineValue = baseline[field];
      if (stableJson(currentValue) !== stableJson(baselineValue)) {
        patch[field] = currentValue as never;
      }
    }
    if (Object.keys(patch).length > 1) updated.push(patch);
  }

  const baselineExistingOrder = baselineLayers
    .filter((layer) => currentById.has(layer.id))
    .map((layer) => layer.id);
  const currentExistingOrder = currentLayers
    .filter((layer) => baselineById.has(layer.id))
    .map((layer) => layer.id);
  const sortOrderChanged = currentLayers.some((layer) => {
    const baseline = baselineById.get(layer.id);
    return baseline ? baseline.sort_order !== layer.sort_order : false;
  });
  const orderChanged =
    stableJson(baselineExistingOrder) !== stableJson(currentExistingOrder) || sortOrderChanged;

  const diff: MapLayerDiffRequest = {};
  if (added.length > 0) diff.added = added;
  if (updated.length > 0) diff.updated = updated;
  if (removed.length > 0) diff.removed = removed;
  if (orderChanged) diff.order = currentExistingOrder;

  return { diff, unsupported: false };
}

interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  showBasemapLabels: boolean;
  terrainConfig: MapTerrainConfig | null;
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
  const patchMapLayers = usePatchMapLayers();
  const duplicateMutation = useDuplicateMap();
  const enabledWidgetsQuery = useEnabledWidgets();
  const enabledWidgetIds = useMemo(
    () => enabledWidgetsQuery.data ?? (enabledWidgetsQuery.isLoading ? [] : null),
    [enabledWidgetsQuery.data, enabledWidgetsQuery.isLoading],
  );

  const baselineLayersRef = useRef<MapLayerResponse[]>([]);
  useEffect(() => {
    if (!state.hasUnsavedChanges) {
      baselineLayersRef.current = state.localLayers.map((layer) => ({ ...layer }));
    }
  }, [state.hasUnsavedChanges, state.localLayers]);

  async function handleSave() {
    const {
      mapId: id,
      mapInstanceRef,
      localName,
      localDescription,
      dockNotes,
      localBasemap,
      localLayers,
      showBasemapLabels,
      terrainConfig,
    } = state;
    if (!id) return;

    // Block save if any layer's popup expression references unknown columns.
    // Server-side validation is shape-only (per CONTEXT.md / RESEARCH §4),
    // so the frontend is the primary UX gate for placeholder correctness.
    const invalidLayer = localLayers.find((l) => {
      const cfg = l.popup_config;
      if (!cfg?.enabled || !cfg.expression) return false;
      const columns = (l.dataset_column_info ?? []).map((c) => c.name);
      return !validatePlaceholders(extractPlaceholders(cfg.expression), columns).ok;
    });
    if (invalidLayer) {
      toast.error(t('toasts.popupConfigInvalid'));
      return;
    }

    const map = mapInstanceRef.current;
    const center = map?.getCenter();
    const zoom = map?.getZoom();
    const bearing = map?.getBearing();
    const pitch = map?.getPitch();

    const metadataPayload: MapUpdateRequest = {
      name: localName || undefined,
      description: localDescription.trim() || null,
      notes: dockNotes.trim() || null,
      basemap_style: localBasemap,
      show_basemap_labels: showBasemapLabels,
      terrain_config: terrainConfig,
      center_lng: center?.lng ?? null,
      center_lat: center?.lat ?? null,
      zoom: zoom ?? null,
      bearing: bearing ?? 0,
      pitch: pitch ?? 0,
      widgets: resolveWidgetsPayload(id, queryClient, enabledWidgetIds),
    };
    const fullReplacementPayload: MapUpdateRequest = {
      ...metadataPayload,
      layers: localLayers.map(toLayerInput),
    };

    try {
      const { diff, unsupported } = buildLayerDiff(baselineLayersRef.current, localLayers);
      if (unsupported) {
        await updateMap.mutateAsync({ id, data: fullReplacementPayload });
      } else {
        if (hasDiff(diff)) {
          try {
            await patchMapLayers.mutateAsync({ id, diff });
          } catch (error) {
            if (!isUnsupportedLayerPatchError(error)) throw error;
            await updateMap.mutateAsync({ id, data: fullReplacementPayload });
            baselineLayersRef.current = localLayers.map((layer) => ({ ...layer }));
            toast.success(t('toasts.mapSaved'));
            state.setHasUnsavedChanges(false);
            if (map && id) captureThumbnail(map, id, queryClient, localLayers);
            return;
          }
        }
        await updateMap.mutateAsync({ id, data: metadataPayload });
      }

      baselineLayersRef.current = localLayers.map((layer) => ({ ...layer }));
      toast.success(t('toasts.mapSaved'));
      state.setHasUnsavedChanges(false);

      // Capture thumbnail and upload (fire-and-forget)
      // Use `map` captured before mutate — mapInstanceRef.current may be
      // transiently null during re-render (callback ref identity change).
      if (map && id) {
        captureThumbnail(map, id, queryClient, localLayers);
      }
    } catch {
      toast.error(t('toasts.saveFailed'));
    }
  }

  function handleExportPNG() {
    const map = state.mapInstanceRef.current;
    if (!map) return;

    const doExport = () => {
      // PERF-08 (Phase 274): force a render frame, then read pixels.
      // Mirrors the doCapture pattern: the WebGL canvas no longer retains
      // its drawing buffer, so we register the read on the next render
      // event tick and trigger an immediate repaint.
      const onRender = () => {
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

      map.once('render', onRender);
      map.triggerRepaint();
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
        if (!updateMap.isPending && !patchMapLayers.isPending) handleSaveRef.current();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [patchMapLayers.isPending, updateMap.isPending]);

  return {
    handleSave,
    handleExportPNG,
    handleFork,
    maybeAutoCaptureThumbnail,
    isSaving: updateMap.isPending || patchMapLayers.isPending,
    isForkPending: duplicateMutation.isPending,
    blocker,
  };
}
