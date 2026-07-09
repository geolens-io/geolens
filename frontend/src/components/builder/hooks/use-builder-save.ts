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
import { useEnabledPlugins } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import { getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import { uploadThumbnail, uploadOgImage } from '@/api/maps';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { MapBasemapConfig, MapLayerDiffRequest, MapLayerInput, MapLayerPatch, MapLayerResponse, MapResponse, MapTerrainConfig, MapUpdateRequest } from '@/types/api';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useAuthStore } from '@/stores/auth-store';
import { getDefaultPluginIds, resolveAvailablePluginIds, samePluginIds } from '@/components/map-plugins';
import { prepareLayersForPersistence, type FolderGroupMeta } from '@/components/builder/folder-groups';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
// fix(#430 V-01): capability gate used to detect fields the builder has no editor
// for on a given layer type (see unmanagedNullableFields below).
import { getLayerCapabilities } from '@/lib/layer-capabilities';

/** Center-crop `srcCanvas` to the given target dimensions and return the
 *  resulting offscreen canvas. Crops from the center without distortion
 *  (letterbox / pillarbox math). Supports any target aspect ratio.
 *
 *  SHARE-08 (Phase 1142): extracted from the former inline doCapture crop block
 *  to allow two crops (400×250 thumbnail, 1200×630 OG image) to share one
 *  render event with a single triggerRepaint(). */
function cropResize(srcCanvas: HTMLCanvasElement, targetW: number, targetH: number): HTMLCanvasElement {
  const targetRatio = targetW / targetH;
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
  offscreen.width = targetW;
  offscreen.height = targetH;
  const ctx = offscreen.getContext('2d');
  if (ctx) {
    ctx.drawImage(srcCanvas, cropX, cropY, cropW, cropH, 0, 0, targetW, targetH);
  }
  return offscreen;
}

/** Crop and resize the map canvas to a 400x250 JPEG thumbnail AND a 1200x630
 *  OG image, then upload both.
 *
 *  PERF-08 (Phase 274): we no longer keep preserveDrawingBuffer permanently
 *  enabled. Force one render frame and read pixels from the freshly-painted
 *  canvas. Using `once('render')` is more reliable than relying on the
 *  synchronous post-triggerRepaint state because some browsers async-defer
 *  the repaint to the next animation frame.
 *
 *  SHARE-08 (Phase 1142): the single onRender callback now captures BOTH
 *  targets from the same srcCanvas without a second triggerRepaint (Pitfall #5).
 *  The OG upload is fire-and-forget with its own catch so an OG failure does
 *  not prevent the thumbnail save. */
function doCapture(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
  const onRender = () => {
    try {
      const srcCanvas = map.getCanvas();

      // 400×250 thumbnail — unchanged behavior
      const thumb = cropResize(srcCanvas, 400, 250);
      uploadThumbnail(mapId, thumb.toDataURL('image/jpeg', 0.7)).then(() => {
        queryClient.invalidateQueries({ queryKey: queryKeys.maps.all });
      }).catch(() => {
        // Silent failure for thumbnails
      });

      // 1200×630 OG image — fire-and-forget, isolated failure (SHARE-08)
      const og = cropResize(srcCanvas, 1200, 630);
      uploadOgImage(mapId, og.toDataURL('image/jpeg', 0.85)).catch(() => {
        if (import.meta.env.DEV) console.warn('[og-image] capture upload failed');
      });
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
 *  doCapture. Callers should go through captureThumbnail (debounced wrapper).
 *
 *  POLISH-01 (Phase 1233-01): when `layersRef` is provided and the snapshot `layers`
 *  is empty, the first auto-capture is deferred: we poll `layersRef.current` (the
 *  live ref updated every render) until a layer appears, then proceed through
 *  waitForVisibleLayerSources normally. This fixes the new-map + ?add_dataset race
 *  where the 500ms debounce fires before the layer-add effect has run.
 *
 *  Invariants preserved:
 *  - SF-05: a genuinely-empty map (layers stay [] until deadline) falls through
 *    to the existing whenMapIdle path, so we never busy-loop forever.
 *  - SF-07: shouldAutoCapture fires before captureThumbnail; this function does
 *    not touch autoCapturedKeys.
 *  - SP-16: the 500ms debounce is upstream in captureThumbnail; unaffected.
 *  - T-1233-01: the 5000ms bounded deadline + cancellation signal prevent DoS. */
function runCaptureNow(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
  layersRef?: React.RefObject<MapLayerResponse[]>,
) {
  // POLISH-01: defer the first capture when a layer-add is pending (layersRef
  // provided) but no layers have synced yet. Poll the live ref so we pick up
  // the layer that ?add_dataset adds after initializedRef resolves.
  if (layers.length === 0 && layersRef) {
    const deadline = Date.now() + 5000;
    const pollForLayers = () => {
      if (signal?.cancelled) return;
      const live = layersRef.current ?? [];
      if (live.length > 0) {
        // Layers have arrived — proceed through normal source-readiness path.
        waitForVisibleLayerSources(map, live, () => doCapture(map, mapId, queryClient), signal);
        return;
      }
      if (Date.now() >= deadline) {
        // SF-05: genuinely empty after the deadline — fall back to idle path so
        // we never leave an open poll. Re-check cancellation INSIDE the idle
        // callback (WR-02): whenMapIdle can fire up to ~3s later, possibly after
        // an unmount, so the guard must be at capture time, not registration time.
        whenMapIdle(map, () => {
          if (!signal?.cancelled) doCapture(map, mapId, queryClient);
        });
        return;
      }
      setTimeout(pollForLayers, 100);
    };
    pollForLayers();
    return;
  }
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
 *  WR-03 (Phase 1050-rev): this guard is NOT cleared on hook unmount or mapId
 *  change, because doing so re-introduces the SF-07 duplicate-capture bug under
 *  Vite-dev StrictMode (unmount → remount → guard cleared → second PUT fires
 *  after the first's debounce has already settled).
 *
 *  STATE-07 (builder-audit #338 20260626): the guard is now a bounded LRU instead of
 *  an unbounded write-only Set. The just-captured map's key stays resident (so
 *  StrictMode remount is still deduped), but the structure no longer accumulates
 *  one entry per visited map for the lifetime of the tab, and old maps age out
 *  past the cap — so a server-side thumbnail deletion can re-trigger auto-capture
 *  once the user has moved through enough other maps, without a hard reload. The
 *  `__resetThumbnailDebounceForTests` helper clears it in vitest setup. */
/** Phase 1051 WR-07: keyed by `userId:mapId` so a cross-user session does NOT
 *  inherit the previous user's guard entry. Previously keyed by `mapId` only,
 *  which leaked across auth-switch and blocked legitimate auto-captures after
 *  the same browser logged in as a different user with access to the same map. */
const AUTO_CAPTURE_LRU_LIMIT = 64;
const autoCapturedKeys = new Map<string, true>();

function captureThumbnail(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
  layersRef?: React.RefObject<MapLayerResponse[]>,
) {
  // SP-16: clear any prior pending capture for this mapId; the latest call
  // wins (trailing edge), reflecting the final state once the window settles.
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);

  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    // POLISH-01: pass layersRef through so runCaptureNow can defer on the
    // new-map + ?add_dataset path. Save-path callers do not pass layersRef,
    // so they remain on the existing waitForVisibleLayerSources path.
    runCaptureNow(map, mapId, queryClient, layers, signal, layersRef);
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
function shouldAutoCapture(mapId: string, userId: string | null): boolean {
  // Phase 1051 WR-07: key by both userId and mapId. anon users (token only,
  // no resolvable user) collapse to a stable 'anon' bucket so anonymous
  // sessions still benefit from StrictMode dedupe within a single tab.
  const key = `${userId ?? 'anon'}:${mapId}`;
  if (autoCapturedKeys.has(key)) {
    // Refresh recency (re-insert at the tail) so an actively-edited map stays
    // resident through StrictMode unmount/remount churn rather than aging out.
    autoCapturedKeys.delete(key);
    autoCapturedKeys.set(key, true);
    return false;
  }
  autoCapturedKeys.set(key, true);
  // Map preserves insertion order; evict the oldest entries beyond the cap.
  while (autoCapturedKeys.size > AUTO_CAPTURE_LRU_LIMIT) {
    const oldest = autoCapturedKeys.keys().next().value;
    if (oldest === undefined) break;
    autoCapturedKeys.delete(oldest);
  }
  return true;
}

/** Test helper — clear any pending debounced captures AND the SF-07
 *  module-level auto-capture guard so module-level state doesn't leak
 *  across vitest cases. Called from `beforeEach`. */
export function __resetThumbnailDebounceForTests(): void {
  for (const timer of pendingCaptures.values()) clearTimeout(timer);
  pendingCaptures.clear();
  autoCapturedKeys.clear();
}

function resolvePluginsPayload(
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  enabledPluginIds: string[] | null | undefined,
): string[] | null | undefined {
  const active = resolveAvailablePluginIds(
    usePluginStore.getState().activePlugins,
    enabledPluginIds,
  );
  const cached = queryClient.getQueryData<MapResponse>(queryKeys.maps.detail(mapId));
  if (samePluginIds(active, getDefaultPluginIds(enabledPluginIds))) {
    return cached?.plugins == null ? undefined : null;
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

/**
 * fix(#430 V-01): the subset of PATCHABLE_LAYER_FIELDS that (a) the backend treats
 * as explicitly-nullable on a PATCH (`_NULLABLE_PATCH_FIELDS` — an explicit
 * `null` NULLs the column, an omitted key leaves it untouched, per
 * `service_diff.py`) AND (b) this specific layer's TYPE has no builder editor
 * for at all — e.g. `style_config` on a raster layer (RasterLayerControls
 * never writes style_config; only vector layers get LayerStyleEditor/
 * DataDrivenStyleEditor/renderAs).
 *
 * When the local layer object simply never carried one of these fields (it
 * was never populated because no editor manages it for this layer kind),
 * `normalizeDemStyleConfig()` and the `?? null` fallbacks in toLayerSnapshot
 * collapse that "never set" state into an explicit `null` — indistinguishable
 * from a deliberate user clear once serialized. If the server-side baseline
 * had real data (e.g. a style_config written by an earlier session, or a
 * migration), the per-field diff below would otherwise emit an explicit
 * `null` and the backend would NULL out real data the builder never touched.
 * Gating on layer-type capability lets buildLayerDiff tell "genuinely
 * unmanaged" apart from "user cleared it via the UI" without threading an
 * extra flag through every layer object.
 */
function unmanagedNullableFields(
  layer: Pick<MapLayerResponse, 'layer_type' | 'dataset_record_type' | 'dataset_geometry_type'>,
): Set<PatchableLayerField> {
  const caps = getLayerCapabilities(layer);
  const fields = new Set<PatchableLayerField>();
  if (!caps.supportsStyleEditor) fields.add('style_config');
  if (!caps.supportsFilterEditor) fields.add('filter');
  if (!caps.supportsLabelEditor) fields.add('label_config');
  // Popup config is offered whenever EITHER the filter or label editor is
  // available — mirrors LayerEditorPanel's `availableTabs` popup-tab gate.
  if (!caps.supportsFilterEditor && !caps.supportsLabelEditor) fields.add('popup_config');
  return fields;
}

function toLayerInput(layer: MapLayerResponse): MapLayerInput {
  return {
    // fix(#430 codex): carry the layer id so a full PUT reconciles rows in
    // place (V-14) instead of regenerating every layer UUID. Builder layer ids
    // are always server-issued UUIDs (instant-add POSTs before local state).
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
    style_config: normalizeDemStyleConfig(layer.style_config, layer.is_dem),
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
    style_config: normalizeDemStyleConfig(layer.style_config, layer.is_dem),
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
  groupMeta: Record<string, FolderGroupMeta> = {},
): LayerDiffResult {
  const baselinePersistedLayers = prepareLayersForPersistence(baselineLayers);
  const currentPersistedLayers = prepareLayersForPersistence(currentLayers, groupMeta);
  const baselineById = new Map(baselinePersistedLayers.map((layer) => [layer.id, toLayerSnapshot(layer)]));
  const currentById = new Map(currentPersistedLayers.map((layer) => [layer.id, layer]));

  const added = currentPersistedLayers
    .filter((layer) => !baselineById.has(layer.id))
    .map(toLayerInput);
  const removed = baselinePersistedLayers
    .filter((layer) => !currentById.has(layer.id))
    .map((layer) => layer.id);
  const updated: MapLayerPatch[] = [];

  for (const layer of currentPersistedLayers) {
    const baseline = baselineById.get(layer.id);
    if (!baseline) continue;

    const unmanaged = unmanagedNullableFields(layer);
    const currentSnapshot = toLayerSnapshot(layer);
    const patch: MapLayerPatch = { id: layer.id };
    for (const field of PATCHABLE_LAYER_FIELDS) {
      const currentValue = currentSnapshot[field];
      const baselineValue = baseline[field];
      if (stableJson(currentValue) === stableJson(baselineValue)) continue;

      // fix(#430 V-01): never emit an explicit null-out for a nullable field this
      // layer's type has no editor for — omit the key entirely (server keeps
      // whatever it already has) instead of nulling real data. Only applies
      // in the null/erasure direction; a genuinely new non-null value for an
      // unmanaged field (shouldn't normally happen) still patches through.
      if (currentValue == null && unmanaged.has(field)) continue;

      patch[field] = currentValue as never;
    }
    if (Object.keys(patch).length > 1) updated.push(patch);
  }

  const baselineExistingOrder = baselinePersistedLayers
    .filter((layer) => currentById.has(layer.id))
    .map((layer) => layer.id);
  const currentExistingOrder = currentPersistedLayers
    .filter((layer) => baselineById.has(layer.id))
    .map((layer) => layer.id);
  const sortOrderChanged = currentPersistedLayers.some((layer) => {
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
  groupMeta?: Record<string, FolderGroupMeta>;
  localBasemap: string;
  showBasemapLabels: boolean;
  basemapConfig: MapBasemapConfig | null;
  terrainConfig: MapTerrainConfig | null;
  localName: string;
  localDescription: string;
  /** ENH-06: custom map-level legend title. Null = no override. */
  legendTitle: string | null;
  dockNotes: string;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
  hasThumbnail?: boolean;
  /** fix(#392): callback ref populated by useBuilderSave and invoked by
   *  useBuilderLayers' layer-create paths (handleAddDataset / handleDuplicateRendering)
   *  so the server-created layer is registered into the Save-diff baseline
   *  the moment it is inserted — see the effect below for the full rationale. */
  saveBaselineSyncRef: React.MutableRefObject<(layer: MapLayerResponse) => void>;
  /** POLISH-01 (Phase 1233-01): set to true when the builder was opened with a
   *  ?add_dataset URL param so the first auto-capture is deferred until the
   *  layer-add effect has synced localLayers. Omit (or set false) for normal
   *  maps — existing behavior is preserved (empty map → idle path). */
  pendingLayerAdd?: boolean;
}

export function useBuilderSave(state: SaveState) {
  const { t } = useTranslation('builder');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const updateMap = useUpdateMap();
  const patchMapLayers = usePatchMapLayers();
  const duplicateMutation = useDuplicateMap();
  const [lastSaveFailed, setLastSaveFailed] = useState(false);
  const { isEnterprise } = useEdition();
  const enabledPluginsQuery = useEnabledPlugins();
  const enabledPluginIds = useMemo(
    () => enabledPluginsQuery.data ?? (enabledPluginsQuery.isLoading ? [] : null),
    [enabledPluginsQuery.data, enabledPluginsQuery.isLoading],
  );

  const baselineLayersRef = useRef<MapLayerResponse[]>([]);
  useEffect(() => {
    if (!state.hasUnsavedChanges) {
      baselineLayersRef.current = state.localLayers.map((layer) => ({ ...layer }));
    }
  }, [state.hasUnsavedChanges, state.localLayers]);

  useEffect(() => {
    // fix(#392): let layer-create paths register the server-created layer into the
    // Save-diff baseline. Marking the map dirty in the same update that inserts a
    // POST-created layer (the WR-02/CR-01 sort_order fix) otherwise leaves this
    // baseline unaware of the new server id, so buildLayerDiff reports it as
    // diff.added and the PATCH endpoint creates a duplicate. Register the PURE
    // server layer (no local grouping/reorder) so grouping/order still diff normally.
    state.saveBaselineSyncRef.current = (layer: MapLayerResponse) => {
      if (!baselineLayersRef.current.some((l) => l.id === layer.id)) {
        baselineLayersRef.current = [...baselineLayersRef.current, { ...layer }];
      }
    };
  });

  async function handleSave() {
    const {
      mapId: id,
      mapInstanceRef,
      localName,
      localDescription,
      legendTitle,
      dockNotes,
      localBasemap,
      localLayers,
      groupMeta = {},
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
      plugins: resolvePluginsPayload(id, queryClient, enabledPluginIds),
      // ENH-06: persist the custom legend title. Empty/null clears it server-side.
      legend_title: legendTitle && legendTitle.trim() ? legendTitle.trim() : null,
    };
    const persistableLayers = prepareLayersForPersistence(localLayers, groupMeta);
    const fullReplacementPayload: MapUpdateRequest = {
      ...metadataPayload,
      layers: persistableLayers.map(toLayerInput),
    };

    try {
      const { diff, unsupported } = buildLayerDiff(baselineLayersRef.current, localLayers, groupMeta);
      if (unsupported) {
        await updateMap.mutateAsync({ id, data: fullReplacementPayload });
      } else {
        if (hasDiff(diff)) {
          try {
            await patchMapLayers.mutateAsync({ id, diff });
          } catch (error) {
            if (!isUnsupportedLayerPatchError(error)) throw error;
            // fix(#430 V-01): this fallback converts a rejected partial PATCH into a
            // full PUT replacement (every layer re-serialized via toLayerInput,
            // including a lossy style_config/paint round-trip and — per V-14 —
            // fresh layer-row UUIDs). It used to report the same plain
            // "Map saved" success toast as a normal save, silently hiding that
            // a full re-sync occurred. Surface it instead so the user knows to
            // double-check layer styling rather than trusting a clean save.
            await updateMap.mutateAsync({ id, data: fullReplacementPayload });
            baselineLayersRef.current = localLayers.map((layer) => ({ ...layer }));
            toast.warning(t('toasts.mapSavedFullResync', {
              defaultValue: 'Map saved, but required a full re-sync. Please double-check layer styling.',
            }));
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
      // PERF-08 (Phase 274): force a render frame, then composite chrome
      // (title, legend, branding) onto an offscreen canvas. The WebGL canvas
      // no longer retains its drawing buffer, so we register the read on the
      // next render event tick and trigger an immediate repaint.
      const onRender = () => {
        try {
          const srcCanvas = map.getCanvas();
          const dpr = window.devicePixelRatio || 1;
          const mapWidth = srcCanvas.width;
          const mapHeight = srcCanvas.height;

          // All chrome metrics are expressed in srcCanvas pixel space (dpr-scaled).
          const pad = 20 * dpr;
          const title = (state.localName || '').trim();
          const description = (state.localDescription || '').trim();
          const titleFontPx = 28 * dpr;
          const descFontPx = 14 * dpr;
          const titleBlockH = title ? (description ? 84 * dpr : 56 * dpr) : 0;

          const legendLayers = state.localLayers.filter(
            (l) => l.visible && l.show_in_legend !== false,
          );
          const legendHeaderH = legendLayers.length > 0 ? 32 * dpr : 0;
          const legendRowH = 22 * dpr;
          const legendBlockH =
            legendLayers.length > 0
              ? 12 * dpr + legendHeaderH + legendLayers.length * legendRowH + 12 * dpr
              : 0;

          const showBranding = !isEnterprise;
          const footerH = showBranding ? 32 * dpr : 0;

          const totalH = Math.round(titleBlockH + mapHeight + legendBlockH + footerH);
          const totalW = Math.round(mapWidth);

          const off = document.createElement('canvas');
          off.width = totalW;
          off.height = totalH;
          const ctx = off.getContext('2d');
          if (!ctx) {
            toast.error(t('toasts.exportFailed'));
            return;
          }

          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, totalW, totalH);

          let cursorY = 0;
          ctx.textBaseline = 'top';

          if (title) {
            ctx.fillStyle = '#0a0a0a';
            ctx.font = `700 ${titleFontPx}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            ctx.fillText(title, pad, cursorY + pad);
            if (description) {
              ctx.fillStyle = '#666666';
              ctx.font = `400 ${descFontPx}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
              ctx.fillText(description, pad, cursorY + pad + titleFontPx + 8 * dpr);
            }
            cursorY += titleBlockH;
          }

          ctx.drawImage(srcCanvas, 0, cursorY);
          cursorY += mapHeight;

          if (legendLayers.length > 0) {
            cursorY += 12 * dpr;
            ctx.fillStyle = '#0a0a0a';
            ctx.font = `600 ${14 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            ctx.fillText(t('export.legendHeader', { defaultValue: 'Legend' }), pad, cursorY);
            cursorY += legendHeaderH;
            ctx.font = `400 ${13 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            const swatchSize = 14 * dpr;
            for (const layer of legendLayers) {
              // fix(#424): mirror the on-screen legend swatch — draw a gradient for
              // multi-stop ramps (graduated/categorical/heatmap) and use the real
              // stroke color as the border so hollow-circle styles (light fill +
              // colored ring, e.g. #fff7ed fill / #ea580c stroke) don't export blank.
              const colors = getLayerColors(layer);
              const hints = extractStyleHints(
                layer.paint ?? {},
                layer.layout ?? {},
                layer.dataset_geometry_type,
                undefined,
                layer.style_config,
              );
              // A stroke the user turned off lives in builder.strokeDisabled (which
              // leaves a stale circle-stroke-color in paint) or a zeroed width, but
              // extractStyleHints only honors paint['_stroke-disabled']. Resolve it the
              // way the map adapters do so the export doesn't reintroduce a hidden ring.
              const builder = layer.style_config?.builder;
              const strokeHidden =
                (builder?.strokeDisabled ?? !!layer.paint?.['_stroke-disabled']) ||
                layer.paint?.['circle-stroke-width'] === 0 ||
                layer.paint?.['_outline-width'] === 0;
              const rowY = cursorY + (legendRowH - swatchSize) / 2;
              const solidFill = colors.find((c) => !!c) || '#6366f1';
              let filled = false;
              if (colors.length > 1) {
                try {
                  const grad = ctx.createLinearGradient(pad, 0, pad + swatchSize, 0);
                  colors.forEach((c, i) => grad.addColorStop(i / (colors.length - 1), c));
                  ctx.fillStyle = grad;
                  filled = true;
                } catch {
                  // An unparseable ramp color makes addColorStop throw; fall back to a
                  // solid swatch rather than aborting the whole export.
                }
              }
              if (!filled) ctx.fillStyle = solidFill;
              ctx.fillRect(pad, rowY, swatchSize, swatchSize);
              ctx.strokeStyle = (!strokeHidden && hints.strokeColor) || 'rgba(0,0,0,0.35)';
              ctx.lineWidth = Math.max(1, dpr);
              ctx.strokeRect(pad, rowY, swatchSize, swatchSize);
              ctx.fillStyle = '#0a0a0a';
              ctx.fillText(
                layer.display_name || layer.dataset_name,
                pad + swatchSize + 10 * dpr,
                cursorY + (legendRowH - 13 * dpr) / 2,
              );
              cursorY += legendRowH;
            }
          }

          if (showBranding) {
            const footerText = t('export.poweredBy', { defaultValue: 'Powered by GeoLens' });
            ctx.fillStyle = '#999999';
            ctx.font = `400 ${12 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            ctx.textBaseline = 'middle';
            const metrics = ctx.measureText(footerText);
            ctx.fillText(footerText, totalW - metrics.width - pad, totalH - footerH / 2);
          }

          off.toBlob((blob) => {
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
    // Phase 1051 WR-07: pass the current user id so the guard key is scoped per
    // user. The previous mapId-only key persisted across logout/login and blocked
    // legitimate captures after auth switch.
    const userId = useAuthStore.getState().user?.id ?? null;
    if (!shouldAutoCapture(state.mapId, userId)) {
      thumbCaptured.current = true; // keep the instance ref consistent
      return;
    }
    thumbCaptured.current = true;
    captureSignalRef.current = { cancelled: false };
    // POLISH-01: when a layer-add is pending (new-map + ?add_dataset path), pass
    // the live localLayersRef so runCaptureNow can defer the capture until layers
    // arrive. For all other paths, layersRef is undefined → existing behavior.
    const layersRef = state.pendingLayerAdd ? localLayersRef : undefined;
    captureThumbnail(map, state.mapId, queryClient, localLayersRef.current, captureSignalRef.current, layersRef);
  }, [state.hasThumbnail, state.mapId, state.pendingLayerAdd, queryClient]);

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
        // EASY-02 (Phase 1138-01): preventDefault fires unconditionally to suppress
        // the browser "Save Page As" dialog whenever Cmd/Ctrl+S is pressed in the builder,
        // regardless of pending state or open modals.
        e.preventDefault();
        // EASY-02 (Phase 1138-01): no-op when any Radix dialog/sheet is open so
        // typing Cmd+S inside the Share dialog or Add Dataset modal does not race
        // a layer mutation against open-modal context. Radix sets
        // data-state="open" on its content element; we check both the role-dialog
        // selector (covers Dialog, AlertDialog) and the Sheet-specific data-slot
        // selector (covers Sheet, which uses role="dialog" but also data-slot="sheet-content").
        const dialogOpen = document.querySelector('[role="dialog"][data-state="open"]');
        if (dialogOpen) return;
        if (updateMap.isPending || patchMapLayers.isPending) return;
        handleSaveRef.current();
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
