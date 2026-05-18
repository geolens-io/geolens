import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getSourceIdForLayer } from '@/components/builder/map-sync';
import { ApiError } from '@/api/client';
import { useUpdateMap, useDuplicateMap, usePatchMapLayers } from '@/hooks/use-maps';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { uploadThumbnail } from '@/api/maps';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { MapBasemapConfig, MapLayerDiffRequest, MapLayerInput, MapLayerPatch, MapLayerResponse, MapResponse, MapTerrainConfig, MapUpdateRequest } from '@/types/api';
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
    .map((layer) => getSourceIdForLayer(layer));

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

/** Run a thumbnail capture immediately for the given args.
 *  PERF-08 (Phase 274): doCapture uses map.triggerRepaint() + map.once('render')
 *  to read pixels from a freshly-painted canvas (no permanent preserveDrawingBuffer).
 *  Auto-capture can run before BuilderMap has synced GeoLens sources, so we wait
 *  for visible layer sources first via waitForVisibleLayerSources before calling
 *  doCapture. Callers should go through captureThumbnail (debounced wrapper). */
function runCaptureNow(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
) {
  waitForVisibleLayerSources(map, layers, () => doCapture(map, mapId, queryClient), signal);
}

/** SP-16: 500ms trailing-edge debounce around captureThumbnail.
 *  Smoke evidence showed two back-to-back `PUT /maps/<id>/thumbnail/`
 *  requests when a single layer-add triggered both the save-path capture
 *  and a chained auto-capture. Coalesce all invocations within a 500ms
 *  window into one capture for the most-recent args. Keyed by mapId so
 *  concurrent edits to different maps don't collide. */
const THUMBNAIL_DEBOUNCE_MS = 500;
const pendingCaptures = new Map<string, ReturnType<typeof setTimeout>>();

/** SF-07 (Phase 1050-04): module-level guard that tracks per-mapId
 *  auto-capture initiation. Survives Vite-dev StrictMode hook unmount /
 *  remount cycles where the per-hook-instance `thumbCaptured` ref would
 *  otherwise reset to false and allow a second PUT after the first
 *  capture's debounce window has already fired. The module-level
 *  `pendingCaptures` Map alone is not sufficient: it's cleared the
 *  moment the trailing-edge setTimeout fires, so a second hook instance
 *  arriving even one ms later sees `pendingCaptures.get(mapId) ===
 *  undefined` and schedules a fresh capture. We need a separate set that
 *  remembers "an auto-capture has already been initiated for this map in
 *  this session" until an explicit reset.
 *
 *  WR-03 (Phase 1050-rev): this set is deliberately WRITE-ONLY in
 *  production code. We do NOT clear it on hook unmount or mapId change,
 *  because doing so re-introduces the SF-07 duplicate-capture bug under
 *  Vite-dev StrictMode (unmount → remount → guard cleared → second PUT
 *  fires after the first's debounce has already settled). The only
 *  in-app recovery path is a hard reload (which re-evaluates the
 *  module). Server-side thumbnail deletion or admin re-trigger therefore
 *  requires the user to reload the editor; this is a deliberate
 *  trade-off favouring the more-frequent StrictMode-safety case. The
 *  `__resetThumbnailDebounceForTests` helper clears the set in vitest
 *  setup. */
const autoCapturedMapIds = new Set<string>();

function captureThumbnail(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
) {
  // SP-16: clear any prior pending capture for this mapId; the latest call
  // wins (trailing edge), reflecting the final state once the window settles.
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);

  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    runCaptureNow(map, mapId, queryClient, layers, signal);
  }, THUMBNAIL_DEBOUNCE_MS);

  pendingCaptures.set(mapId, timer);
}

/** SF-07 (Phase 1050-04): module-scoped predicate that decides whether an
 *  auto-capture should be initiated for this mapId in this session.
 *  Returns true on the FIRST call for a given mapId (and marks the id as
 *  taken); returns false on every subsequent call until the guard is
 *  cleared. Callers should run this BEFORE `captureThumbnail()` so a
 *  StrictMode-driven remount cannot bypass it. The trailing-edge debounce
 *  in `captureThumbnail` still applies for the legitimate first call. */
function shouldAutoCapture(mapId: string): boolean {
  if (autoCapturedMapIds.has(mapId)) return false;
  autoCapturedMapIds.add(mapId);
  return true;
}

/** Test helper — clear any pending debounced captures AND the SF-07
 *  module-level auto-capture guard so module-level state doesn't leak
 *  across vitest cases. Called from `beforeEach`. */
export function __resetThumbnailDebounceForTests(): void {
  for (const timer of pendingCaptures.values()) clearTimeout(timer);
  pendingCaptures.clear();
  autoCapturedMapIds.clear();
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

export type BuilderSaveStatus = 'saved' | 'unsaved' | 'saving' | 'failed';

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
  basemapConfig: MapBasemapConfig | null;
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
  const [lastSaveFailed, setLastSaveFailed] = useState(false);
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
      basemapConfig,
      terrainConfig,
    } = state;
    if (!id) return;
    setLastSaveFailed(false);

    // Block save if any layer's popup expression references unknown columns.
    // Server-side validation is shape-only (per CONTEXT.md / RESEARCH §4),
    // so the frontend is the primary UX gate for placeholder correctness.
    const invalidLayer = localLayers.find((l) => {
      const cfg = l.popup_config;
      if (!cfg?.enabled || !cfg.expression) return false;
      // Skip validation when column metadata is absent — the server is the authoritative gate.
      if (!l.dataset_column_info) return false;
      const columns = l.dataset_column_info.map((c) => c.name);
      return !validatePlaceholders(extractPlaceholders(cfg.expression), columns).ok;
    });
    if (invalidLayer) {
      const layerName = invalidLayer.display_name ?? t('toasts.layerFallbackName');
      toast.error(t('toasts.popupConfigInvalidNamed', { layerName }), { id: 'popup-config-invalid', duration: 6000 });
      return;
    }

    const map = mapInstanceRef.current;
    const center = map?.getCenter();
    const zoom = map?.getZoom();
    const bearing = map?.getBearing();
    const pitch = map?.getPitch();

    // Phase 1051 UX-03: basemap_position is encoded as a field on basemapConfig
    // (MapBasemapConfig.basemap_position jsonb), so it round-trips through the
    // wholesale basemap_config pass-through below without a dedicated field.
    // Legacy maps load with basemap_position=undefined and default to 'bottom'
    // on the read path (see use-builder-layers.ts handleReorder + the
    // UnifiedStackPanel basemapPosition default).
    const metadataPayload: MapUpdateRequest = {
      name: localName || undefined,
      description: localDescription.trim() || null,
      notes: dockNotes.trim() || null,
      basemap_style: localBasemap,
      show_basemap_labels: showBasemapLabels,
      basemap_config: basemapConfig,
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
    } catch (err) {
      setLastSaveFailed(true);
      // Detect FastAPI 422 popup_config rejection and surface a structured toast.
      // err.body is the raw detail value from the response (may be an array of
      // {loc, msg, type} objects for validation errors). Any unexpected shape
      // falls through to the generic saveFailed path — do not throw here.
      if (
        err instanceof ApiError &&
        err.status === 422 &&
        Array.isArray(err.body)
      ) {
        const popupLocItem = (err.body as Array<{ loc?: unknown[]; msg?: string; type?: string }>)
          .find((item) => Array.isArray(item.loc) && item.loc.includes('popup_config'));
        if (popupLocItem && Array.isArray(popupLocItem.loc)) {
          const loc = popupLocItem.loc as Array<string | number>;
          const popupIdx = loc.indexOf('popup_config');
          const field = loc.slice(popupIdx).join('.');
          toast.error(t('toasts.popupConfigBackendRejected', { field }), {});
          return;
        }
      }
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
    // SF-07: the per-instance `thumbCaptured` ref doesn't survive a
    // Vite-dev StrictMode hook unmount / remount, so a second hook
    // instance for the same mapId can re-enter here with a fresh ref.
    // The module-level `shouldAutoCapture` guard owns the
    // "already initiated for this mapId this session" invariant.
    if (!shouldAutoCapture(state.mapId)) {
      thumbCaptured.current = true; // keep the instance ref consistent
      return;
    }
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

  const isSaving = updateMap.isPending || patchMapLayers.isPending;
  const saveStatus: BuilderSaveStatus = isSaving
    ? 'saving'
    : lastSaveFailed
      ? 'failed'
      : state.hasUnsavedChanges
        ? 'unsaved'
        : 'saved';

  return {
    handleSave,
    handleExportPNG,
    handleFork,
    maybeAutoCaptureThumbnail,
    isSaving,
    saveStatus,
    isSaveRetryable: saveStatus === 'failed',
    isForkPending: duplicateMutation.isPending,
    blocker,
  };
}
