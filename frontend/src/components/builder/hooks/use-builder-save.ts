import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getSourceIdForLayer, TERRAIN_SOURCE_ID } from '@/components/builder/map-sync';
import { readMapCamera, sameMapCamera, type BuilderCamera } from '@/components/builder/builder-camera';
import { hasGlobeSpaceBackdrop } from '@/components/builder/map-composition-sync';
import { ApiError } from '@/api/client';
import { mapDetailQuery, useUpdateMap, useDuplicateMap, usePatchMapLayers } from '@/hooks/use-maps';
import { useEnabledPlugins } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import { demChipGlyph, getLayerColors } from '@/components/map/layer-icons';
import { getMap, uploadThumbnail, uploadOgImage } from '@/api/maps';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { MapBasemapConfig, MapLayerDiffRequest, MapLayerInput, MapLayerPatch, MapLayerResponse, MapResponse, MapTerrainConfig, MapUpdateRequest } from '@/types/api';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useAuthStore } from '@/stores/auth-store';
import { getDefaultPluginIds, resolveAvailablePluginIds, samePluginIds } from '@/components/map-plugins';
import { legendFacts, rampGradient } from '@/components/map/legend-facts';
import { syntheticTerrainEntry } from '@/components/builder/terrain-legend';
import { getPersistedFolderGroup, hydrateFolderGroupLayers, prepareLayersForPersistence, stampPersistedFolderGroupExpanded, type FolderGroupMeta } from '@/components/builder/folder-groups';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import { MAP_COLORS } from '@/lib/map-colors';
// The rendered-image paths composite from the WebGL canvas, which no DOM
// attribution control can reach. See lib/map-image-attribution.
import {
  attributionBandHeightBudget,
  drawAttributionBand,
  drawAttributionOverlay,
  measureAttributionBand,
  readRenderedAttribution,
  OG_ATTRIBUTION,
  THUMBNAIL_ATTRIBUTION,
} from '@/lib/map-image-attribution';
// Detects fields the builder has no editor for on a given layer type.
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { classifyApiError } from '@/lib/error-map';
import {
  canonicalDashboard,
  dashboardPayload,
  firstWidgetProblem,
  type DashboardDraft,
} from '@/components/builder/dashboard-draft';

/** Center-crop `srcCanvas` to the target dimensions without distortion
 *  (letterbox / pillarbox math), for any aspect ratio.
 *
 *  `backdrop` is painted under the crop when the globe space backdrop is on
 *  screen. The WebGL canvas is transparent wherever a ray missed the planet,
 *  so without it the sphere lands on white (composited) or black (JPEG)
 *  instead of the space color the map shows. */
function cropResize(
  srcCanvas: HTMLCanvasElement,
  targetW: number,
  targetH: number,
  backdrop?: string,
): HTMLCanvasElement {
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
    if (backdrop) {
      ctx.fillStyle = backdrop;
      ctx.fillRect(0, 0, targetW, targetH);
    }
    ctx.drawImage(srcCanvas, cropX, cropY, cropW, cropH, 0, 0, targetW, targetH);
  }
  return offscreen;
}

/** Channel stddev below this reads as "no content". Blank uploads measured
 *  0.00 and 1.88; the flattest real thumbnail 22.9; a bare world-basemap
 *  capture ~24. 4 sits far from both sides, so a minimal map (open ocean on
 *  a flat basemap) still clears it while a frame that never painted cannot. */
export const BLANK_CHANNEL_STDDEV = 4;

/** Stddev alone rejects legitimately sparse maps: a lone point on the "No
 *  basemap" background computes to ~2. A low-variance frame therefore gets a
 *  second chance: count pixels deviating from the mean color by this delta.
 *  Blank frames have none (a smooth gradient at stddev 1.88 spans ~±3), a
 *  real point feature deviates by 100+ across its footprint, and 8 pixels is
 *  far above readback noise and below any visible feature. */
const SPARSE_CHANNEL_DELTA = 25;
export const SPARSE_PIXEL_COUNT = 8;

/** Max per-channel standard deviation over RGBA data, scanning every pixel
 *  (sampling can miss a dot). Per channel rather than luminance, because
 *  isoluminant hue changes (red/green at equal lightness) are invisible to a
 *  luminance statistic. Pure so it is testable without a canvas. */
export function maxChannelStddev(rgba: Uint8ClampedArray | number[]): number {
  const sum = [0, 0, 0];
  const sumSq = [0, 0, 0];
  let n = 0;
  for (let i = 0; i + 2 < rgba.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      const v = rgba[i + c];
      sum[c] += v;
      sumSq[c] += v * v;
    }
    n++;
  }
  if (n === 0) return 0;
  let max = 0;
  for (let c = 0; c < 3; c++) {
    const mean = sum[c] / n;
    max = Math.max(max, Math.sqrt(Math.max(0, sumSq[c] / n - mean * mean)));
  }
  return max;
}

/** Whether RGBA pixel data reads as a frame nothing painted: low variance in
 *  every channel and no cluster of pixels off the mean color (the sparse-map
 *  rescue above). */
export function isBlankPixelData(rgba: Uint8ClampedArray | number[]): boolean {
  if (maxChannelStddev(rgba) >= BLANK_CHANNEL_STDDEV) return false;
  const sum = [0, 0, 0];
  let n = 0;
  for (let i = 0; i + 2 < rgba.length; i += 4) {
    sum[0] += rgba[i];
    sum[1] += rgba[i + 1];
    sum[2] += rgba[i + 2];
    n++;
  }
  if (n === 0) return false; // cannot judge empty data — fail open
  const mean = [sum[0] / n, sum[1] / n, sum[2] / n];
  let deviants = 0;
  for (let i = 0; i + 2 < rgba.length; i += 4) {
    const dev = Math.max(
      Math.abs(rgba[i] - mean[0]),
      Math.abs(rgba[i + 1] - mean[1]),
      Math.abs(rgba[i + 2] - mean[2]),
    );
    if (dev > SPARSE_CHANNEL_DELTA && ++deviants >= SPARSE_PIXEL_COUNT) {
      return false;
    }
  }
  return true;
}

/** Whether a captured frame is effectively a solid fill.
 *
 *  The capture pipeline is fail-open at every stage (waitForVisibleLayerSources
 *  proceeds on its 5s deadline, whenMapIdle on its 3s timeout), so a slow
 *  first render can leave doCapture reading an unpainted canvas. Uploading it
 *  makes the failure permanent: the auto-capture gate is `hasThumbnail`, so
 *  one blank upload disqualifies the map from every future attempt.
 *
 *  Fails open: if the 2D context or pixel data is unavailable, reports "not
 *  blank" so the upload proceeds. */
export function isEffectivelyBlank(canvas: HTMLCanvasElement): boolean {
  try {
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    return isBlankPixelData(data);
  } catch {
    return false;
  }
}

/** Who asked for this capture. The blank-frame guard applies only to 'auto'
 *  captures, which fire on first open, where a uniform frame means the
 *  unpainted-canvas race. On an explicit save the map is painted, so a
 *  uniform frame is its true appearance; skipping the upload would leave a
 *  stale thumbnail with `hasThumbnail` true, and no retry would correct it. */
type CaptureTrigger = 'auto' | 'save';

/** Whether the entire source frame reads as unpainted.
 *
 *  An unpainted canvas is blank everywhere, so the full frame is measured
 *  once. Judging the crops individually would let content only in the
 *  top/bottom strips make the thumbnail crop real and the wider OG crop
 *  uniform; the thumbnail upload flips `hasThumbnail` and the skipped OG
 *  could never retry. Once the frame is painted, every crop must upload.
 *
 *  WebGL pixels are unreadable through 2D APIs on the source itself, so the
 *  frame is copied into a 2D canvas bounded to ~1M pixels: a native copy on a
 *  DPR-2 2560×1440 display is ~14.7M pixels (over 110 MiB of RGBA), and an
 *  allocation failure would fail open into the blank upload this guard
 *  prevents. The downscale keeps both classifications valid: an unpainted
 *  frame is uniform at every scale, and drawImage blends rather than drops,
 *  so a feature of roughly 3×3 effective pixels or more still rescues.
 *  Smaller reads blank, which on auto-capture means skip-and-retry. Fails
 *  open: unreadable pixels never block uploads. */
const FRAME_SAMPLE_PIXEL_BUDGET = 1_000_000;

function isCanvasFrameBlank(src: HTMLCanvasElement): boolean {
  try {
    const scale = Math.min(1, Math.sqrt(FRAME_SAMPLE_PIXEL_BUDGET / (src.width * src.height || 1)));
    const off = document.createElement('canvas');
    off.width = Math.max(1, Math.round(src.width * scale));
    off.height = Math.max(1, Math.round(src.height * scale));
    const ctx = off.getContext('2d');
    if (!ctx) return false;
    ctx.drawImage(src, 0, 0, off.width, off.height);
    return isEffectivelyBlank(off);
  } catch {
    return false;
  }
}

/** Crop and resize the map canvas to a 400x250 JPEG thumbnail and a 1200x630
 *  OG image, then upload both.
 *
 *  Forces one render frame and reads pixels from the freshly painted canvas
 *  (no permanent preserveDrawingBuffer). `once('render')` is more reliable
 *  than the synchronous post-triggerRepaint state because some browsers defer
 *  the repaint to the next animation frame. Both crops come from the same
 *  srcCanvas. The OG upload is fire-and-forget with its own catch, so an OG
 *  failure doesn't block the thumbnail save. */
function doCapture(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  trigger: CaptureTrigger,
  captureIsStale?: (mapId: string) => boolean,
) {
  const onRender = () => {
    // An edit made after the save, or another map now in the builder, must not
    // reach this map's stored images.
    if (captureIsStale?.(mapId)) {
      rearmAutoCapture(mapId);
      return;
    }
    try {
      const srcCanvas = map.getCanvas();
      // Both crops carry the space backdrop when the map shows one, so a
      // globe map's thumbnail and OG card match the builder.
      const backdrop = hasGlobeSpaceBackdrop(map)
        ? MAP_COLORS.exportImage.globeBackground
        : undefined;

      // Never persist an unpainted auto-captured frame (see CaptureTrigger;
      // isCanvasFrameBlank for why the full frame is measured). Skipping
      // leaves `hasThumbnail` false and re-arms the guard, so the next open of
      // the map retries within the SPA session.
      if (trigger === 'auto' && isCanvasFrameBlank(srcCanvas)) {
        rearmAutoCapture(mapId);
        if (import.meta.env.DEV) {
          console.warn('[thumbnail] capture skipped: frame is effectively blank; will retry on next open');
        }
        return;
      }

      // Both crops carry the credit line, drawn on the canvas because
      // MapLibre's DOM attribution control is invisible to crops of the WebGL
      // canvas. It runs after the blank-frame guard, which measures srcCanvas:
      // a credit must not make an unpainted frame read as painted.
      const credits = readRenderedAttribution(map);

      const thumb = cropResize(srcCanvas, 400, 250, backdrop);
      drawAttributionOverlay(thumb, credits, THUMBNAIL_ATTRIBUTION);
      const og = cropResize(srcCanvas, 1200, 630, backdrop);
      drawAttributionOverlay(og, credits, OG_ATTRIBUTION);

      uploadThumbnail(mapId, thumb.toDataURL('image/jpeg', 0.7)).then(() => {
        // Refetches nothing on the builder route, by design: maps.all is
        // ['maps'] while the builder mounts useMap (['map', id]). The target
        // is the MapsPage browse list (['maps', params]), whose MapCard
        // renders thumbnail_url; it is cached but unmounted here, so marking
        // it stale gets the new thumbnail on screen on return. The builder
        // reads thumbnail_url only as the hasThumbnail auto-capture gate,
        // which shouldAutoCapture's LRU has already settled.
        queryClient.invalidateQueries({ queryKey: queryKeys.maps.all });
      }).catch(() => {
        // Silent failure for thumbnails
      });

      // 1200×630 OG image — fire-and-forget, isolated failure
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

/** Run `fn` immediately if the map is loaded, otherwise wait for the idle
 *  event with a 3-second safety timeout. When `stillLoading` is true at that
 *  timeout, call `onDefer` and leave `fn` to the idle event, which fires once
 *  slow raster tiles have settled. */
function whenMapIdle(
  map: MaplibreMap,
  fn: () => void,
  stillLoading?: () => boolean,
  onDefer?: () => void,
) {
  if (map.loaded()) { fn(); return; }
  let done = false;
  const onIdle = () => { if (done) return; done = true; clearTimeout(timer); fn(); };
  map.once('idle', onIdle);
  const timer = setTimeout(() => {
    if (done) return;
    if (stillLoading?.()) { onDefer?.(); return; }
    done = true;
    map.off('idle', onIdle);
    fn();
  }, 3000);
}

const HELD_SOURCE_TYPES = new Set(['raster', 'raster-dem']);

/** Whether a raster or hillshade source on the map is still loading. Other
 *  source types and ids with no source (folder rows, terrain DEMs) don't hold
 *  a capture. */
function anySourceStillLoading(map: MaplibreMap, sourceIds: string[]): boolean {
  return sourceIds.some((sourceId) => {
    const type = map.getSource(sourceId)?.type;
    return type !== undefined && HELD_SOURCE_TYPES.has(type) && !map.isSourceLoaded(sourceId);
  });
}

/** Sources drawn by style layers that aren't hidden. */
function visibleStyleSourceIds(map: MaplibreMap): string[] {
  return (map.getStyle()?.layers ?? []).flatMap((layer) =>
    'source' in layer && typeof layer.source === 'string' && layer.layout?.visibility !== 'none'
      ? [layer.source]
      : [],
  );
}

/** whenMapIdle, holding the capture while a raster or hillshade source
 *  loads. Every source a visible style layer draws counts, not only the map
 *  layers': a raster basemap and the shared terrain source load outside them.
 *  A deferred capture re-arms auto-capture at once, as the blank-frame guard
 *  does, so a reopen during the wait, or after a capture that never runs, can
 *  schedule its own. */
function whenMapIdleAndRasterLoaded(
  map: MaplibreMap,
  mapId: string,
  sourceIds: string[],
  fn: () => void,
) {
  const stillLoading = () =>
    anySourceStillLoading(map, [
      ...sourceIds,
      TERRAIN_SOURCE_ID,
      ...visibleStyleSourceIds(map),
    ]);
  whenMapIdle(map, fn, stillLoading, () => rearmAutoCapture(mapId));
}

function waitForVisibleLayerSources(
  map: MaplibreMap,
  mapId: string,
  layers: MapLayerResponse[],
  fn: () => void,
  signal?: { cancelled: boolean },
) {
  const visibleSourceIds = layers
    .filter((layer) => layer.visible)
    .map((layer) => getSourceIdForLayer(layer));

  if (visibleSourceIds.length === 0) {
    whenMapIdleAndRasterLoaded(map, mapId, [], fn);
    return;
  }

  const deadline = Date.now() + 5000;

  const poll = () => {
    if (signal?.cancelled) return;
    const sourcesReady = visibleSourceIds.every((sourceId) => !!map.getSource(sourceId));
    if (sourcesReady || Date.now() >= deadline) {
      if (!signal?.cancelled) {
        whenMapIdleAndRasterLoaded(map, mapId, visibleSourceIds, () => { if (!signal?.cancelled) fn(); });
      }
      return;
    }
    setTimeout(poll, 100);
  };

  poll();
}

/** Run a thumbnail capture immediately. Callers should go through
 *  captureThumbnail (debounced wrapper).
 *
 *  Auto-capture can run before BuilderMap has synced GeoLens sources, so it
 *  waits for visible layer sources via waitForVisibleLayerSources before
 *  doCapture. When `layersRef` is provided and the snapshot `layers` is
 *  empty, the first auto-capture is deferred: it polls `layersRef.current`
 *  (the live ref) until a layer appears. This covers the new-map +
 *  ?add_dataset race where the debounce fires before the layer-add effect.
 *
 *  - A genuinely empty map (layers stay [] until the deadline) falls through
 *    to whenMapIdle, so this never polls forever.
 *  - shouldAutoCapture runs before captureThumbnail; this function changes
 *    autoCapturedKeys only to re-arm a capture deferred while a source loads.
 *  - The 5000ms deadline and the cancellation signal bound the polling. A
 *    capture left waiting on a loading raster runs on the next idle event,
 *    where a newer capture, an edit or another map drops it. */
function runCaptureNow(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
  layersRef?: React.RefObject<MapLayerResponse[]>,
  trigger: CaptureTrigger = 'save',
  captureIsStale?: (mapId: string) => boolean,
) {
  // The canvas is read when the capture runs, which can be well after the save.
  // An edit made meanwhile, or a switch to another map, skips it and re-arms
  // auto-capture for a later open.
  const capture = () => {
    if (captureIsStale?.(mapId)) {
      rearmAutoCapture(mapId);
      return;
    }
    doCapture(map, mapId, queryClient, trigger, captureIsStale);
  };
  // Defer the first capture when a layer-add is pending (layersRef provided)
  // but no layers have synced yet.
  if (layers.length === 0 && layersRef) {
    const deadline = Date.now() + 5000;
    const pollForLayers = () => {
      if (signal?.cancelled) return;
      const live = layersRef.current ?? [];
      if (live.length > 0) {
        // Layers have arrived.
        waitForVisibleLayerSources(map, mapId, live, capture, signal);
        return;
      }
      if (Date.now() >= deadline) {
        // Genuinely empty after the deadline: fall back to the idle path.
        // Re-check cancellation inside the idle callback, since whenMapIdle can
        // fire ~3s later, possibly after an unmount.
        whenMapIdleAndRasterLoaded(map, mapId, [], () => {
          if (!signal?.cancelled) capture();
        });
        return;
      }
      setTimeout(pollForLayers, 100);
    };
    pollForLayers();
    return;
  }
  waitForVisibleLayerSources(map, mapId, layers, capture, signal);
}

/** 500ms trailing-edge debounce around captureThumbnail. A single layer-add
 *  could trigger both the save-path capture and a chained auto-capture,
 *  producing two PUT /maps/<id>/thumbnail/ requests. Invocations within the
 *  window coalesce into one capture for the most recent args, keyed by mapId
 *  so edits to different maps don't collide. */
const THUMBNAIL_DEBOUNCE_MS = 500;
const pendingCaptures = new Map<string, ReturnType<typeof setTimeout>>();

/** Per-map auto-capture initiation guard, module-level so it survives
 *  Vite-dev StrictMode unmount/remount cycles (which reset a per-hook ref and
 *  would allow a second PUT). `pendingCaptures` alone isn't enough: it is
 *  cleared when the trailing-edge timeout fires, so a later remount would
 *  schedule a fresh capture. This is not cleared on unmount or mapId change,
 *  for the same reason.
 *
 *  It is a bounded LRU: the just-captured key stays resident (so remounts are
 *  deduped) while old maps age out, so a server-side thumbnail deletion can
 *  re-trigger auto-capture after enough other maps are visited, without a
 *  hard reload. Keys are `userId:mapId` so a different user in the same
 *  browser does not inherit the previous user's entry.
 *  `__resetThumbnailDebounceForTests` clears it in vitest setup. */
const AUTO_CAPTURE_LRU_LIMIT = 64;
const autoCapturedKeys = new Map<string, true>();
// Only the newest capture for a map may run; an older one can still be waiting
// on sources a later save removed.
const captureGenerations = new Map<string, number>();

function captureThumbnail(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  layers: MapLayerResponse[],
  signal?: { cancelled: boolean },
  layersRef?: React.RefObject<MapLayerResponse[]>,
  trigger: CaptureTrigger = 'save',
  captureIsStale?: (mapId: string) => boolean,
) {
  // Clear any prior pending capture for this mapId; the latest call wins.
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);

  const generation = (captureGenerations.get(mapId) ?? 0) + 1;
  captureGenerations.set(mapId, generation);
  const superseded = (id: string) =>
    captureGenerations.get(id) !== generation || !!captureIsStale?.(id);

  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    // Pass layersRef so runCaptureNow can defer on the new-map +
    // ?add_dataset path; save-path callers omit it.
    runCaptureNow(map, mapId, queryClient, layers, signal, layersRef, trigger, superseded);
  }, THUMBNAIL_DEBOUNCE_MS);

  pendingCaptures.set(mapId, timer);
}

/** Whether an auto-capture should be initiated for this mapId in this
 *  session: true on the first call (marking the id taken), false afterwards
 *  until the guard is cleared. Callers run this before `captureThumbnail()`
 *  so a StrictMode remount cannot bypass it. */
export function shouldAutoCapture(mapId: string, userId: string | null): boolean {
  // Anonymous users (no resolvable user) share a stable 'anon' bucket so they
  // still get StrictMode dedupe within a tab.
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

/** Re-arms the guard when doCapture rejects a blank frame, so the retry on
 *  next open survives within an SPA session (the LRU outlives remounts).
 *  Keys are `userId:mapId` and doCapture doesn't know the user, so every
 *  entry for the map is dropped. */
export function rearmAutoCapture(mapId: string): void {
  for (const key of autoCapturedKeys.keys()) {
    if (key.endsWith(`:${mapId}`)) autoCapturedKeys.delete(key);
  }
}

/** Test helper: clear pending debounced captures and the auto-capture guard
 *  so module-level state doesn't leak across vitest cases. */
export function __resetThumbnailDebounceForTests(): void {
  for (const timer of pendingCaptures.values()) clearTimeout(timer);
  pendingCaptures.clear();
  autoCapturedKeys.clear();
  captureGenerations.clear();
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
 * The subset of PATCHABLE_LAYER_FIELDS that the backend treats as
 * explicitly-nullable on a PATCH (`_NULLABLE_PATCH_FIELDS`: an explicit `null`
 * NULLs the column, an omitted key leaves it untouched, per `service_diff.py`)
 * and that this layer's type has no builder editor for at all, e.g.
 * `style_config` on a raster layer.
 *
 * A field the layer never carried is collapsed to an explicit `null` by
 * `normalizeDemStyleConfig()` and the `?? null` fallbacks in toLayerSnapshot,
 * indistinguishable from a deliberate clear. If the server baseline had real
 * data, the per-field diff would emit `null` and NULL out data the builder
 * never touched. Gating on layer-type capability lets buildLayerDiff tell
 * "unmanaged" from "cleared via the UI".
 */
function unmanagedNullableFields(
  layer: Pick<MapLayerResponse, 'layer_type' | 'dataset_record_type' | 'dataset_geometry_type'>,
): Set<PatchableLayerField> {
  const caps = getLayerCapabilities(layer);
  const fields = new Set<PatchableLayerField>();
  if (!caps.supportsStyleEditor) fields.add('style_config');
  if (!caps.supportsFilterEditor) fields.add('filter');
  if (!caps.supportsLabelEditor) fields.add('label_config');
  // Popup config is offered when either the filter or label editor is
  // available (mirrors LayerEditorPanel's `availableTabs`).
  if (!caps.supportsFilterEditor && !caps.supportsLabelEditor) fields.add('popup_config');
  return fields;
}

function toLayerInput(layer: MapLayerResponse): MapLayerInput {
  return {
    // Carry the layer id so a full PUT reconciles rows in place instead of
    // regenerating UUIDs. Builder layer ids are server-issued.
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

// Only a status meaning "this deployment has no layer-diff endpoint" may
// escalate to the lossy full PUT. Status-plus-prose matching would catch the
// shape the backend uses for a stale diff (see isStaleLayerDiffError).
//
// 404 is the compatibility case the PUT fallback exists for: a backend
// predating PATCH /maps/{id}/layers answers 404 for the unknown route
// (FastAPI sends {"detail": "Not Found"}; an edge proxy may send no JSON), and
// without it every layer-edit save there would fail. 405 and 501 are the other
// route-level answers.
const ROUTE_LEVEL_UNSUPPORTED_STATUSES = new Set([404, 405, 501]);
// The one legitimate 404 the route produces for itself: the map is gone, not
// the route. A full PUT would 404 again, so it surfaces as a save failure.
// A stale layer id is a 400 (apply_layer_diff raises ValueError), which
// isStaleLayerDiffError matches by detail, not status alone.
const MAP_NOT_FOUND_DETAIL = /^Map\b.*\bnot found$/i;

/** The backend detail string, preferring the raw `detail` apiFetch stored on
 *  the error; `message` may be localized, so it is only a fallback. */
function apiErrorDetailText(error: ApiError): string {
  return typeof error.body === 'string' ? error.body : error.message;
}

function isUnsupportedLayerPatchError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (!ROUTE_LEVEL_UNSUPPORTED_STATUSES.has(error.status)) return false;
  if (error.status !== 404) return true;
  return !MAP_NOT_FOUND_DETAIL.test(apiErrorDetailText(error));
}

// The details apply_layer_diff raises when the diff names layer ids the map no
// longer has (service_diff.py). Someone else changed the layers since this
// session loaded, so overwriting with the stale snapshot would resurrect what
// they deleted and delete what they added. Recover by re-diffing instead.
const STALE_LAYER_DIFF_DETAIL =
  /Layer diff references layer ids outside this map|Layer order references unknown or removed layers/i;

/** Raised when the stale-diff recovery cannot complete, so the outer catch can
 *  say "the map changed elsewhere" instead of the generic save-failed message. */
class StaleLayerDiffError extends Error {
  constructor() {
    super('Layer diff could not be reconciled with the current map');
    this.name = 'StaleLayerDiffError';
  }
}

function isStaleLayerDiffError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.status !== 400) return false;
  return STALE_LAYER_DIFF_DETAIL.test(apiErrorDetailText(error));
}

/**
 * Drop the parts of a rejected diff the server can no longer apply.
 *
 * Not a fresh `buildLayerDiff` against the refetched map: a layer another
 * session added is absent from `localLayers`, so a full re-diff would emit it
 * as `removed` and delete it. Reconciling the diff already built keeps the
 * recovery additive to server state: ids the server no longer has are
 * dropped and anything this session didn't touch is left alone.
 *
 * `serverLayerIds` is the refetched layer sequence in server sort order, not a
 * membership set, because the order reconciliation needs positions.
 */
export function reconcileLayerDiffWithServer(
  diff: MapLayerDiffRequest,
  serverLayerIds: readonly string[],
): MapLayerDiffRequest {
  const serverIdSet = new Set(serverLayerIds);
  const next: MapLayerDiffRequest = {};
  if (diff.added?.length) next.added = diff.added;
  const updated = diff.updated?.filter((patch) => serverIdSet.has(patch.id));
  if (updated?.length) next.updated = updated;
  const removed = diff.removed?.filter((id) => serverIdSet.has(id));
  if (removed?.length) next.removed = removed;
  const removedSet = new Set(removed ?? []);
  if (diff.order) {
    const order = mergeOrderWithServerSequence(diff.order, serverLayerIds, removedSet);
    if (order.length > 0) next.order = order;
  }
  return next;
}

/**
 * Merge this session's relative order into the server's current sequence
 * instead of sending only the ids this session knows.
 *
 * `apply_layer_diff` numbers the ids it is given from 0 and then appends every
 * surviving layer the order omitted. A bare filter would take server order
 * [A, X, B] with local order [B, A], send [B, A], and strand the remotely
 * added X at the end as [B, A, X]. The stable merge walks the surviving
 * server sequence and substitutes the next locally ordered survivor at each
 * position a locally known layer occupies, so unseen ids keep their server
 * positions: [B, X, A].
 *
 * Ids being removed in the same call are dropped, because the backend rejects
 * an order that names one, and so are ids the server no longer has.
 */
function mergeOrderWithServerSequence(
  localOrder: readonly string[],
  serverLayerIds: readonly string[],
  removedIds: ReadonlySet<string>,
): string[] {
  const serverIdSet = new Set(serverLayerIds);
  const localSurvivors = localOrder.filter(
    (id) => serverIdSet.has(id) && !removedIds.has(id),
  );
  if (localSurvivors.length === 0) return [];
  const localSurvivorSet = new Set(localSurvivors);
  const merged: string[] = [];
  let nextLocal = 0;
  for (const id of serverLayerIds) {
    if (removedIds.has(id)) continue;
    // Positions held by a locally known survivor are filled from the local
    // sequence in order; the counts match by construction.
    merged.push(localSurvivorSet.has(id) ? localSurvivors[nextLocal++] : id);
  }
  return merged;
}

interface LayerDiffResult {
  diff: MapLayerDiffRequest;
  unsupported: boolean;
}

type BuilderSaveStatus = 'saved' | 'unsaved' | 'saving' | 'failed';

/** Bridge between the layer-mutation hooks and useBuilderSave's diff baseline.
 *  `add` registers a layer in the baseline; `remove` is its inverse. */
/** handleSave's side of useBuilderLayers' save fence. */
export interface SaveFence {
  inFlight: (mapId: string) => boolean;
  begin: (mapId: string) => void;
  settle: (mapId: string) => void;
}

export interface SaveBaselineSync {
  add: (layer: MapLayerResponse) => void;
  remove: (layerIds: Iterable<string>) => void;
}

type BaselineRegistration = { add: MapLayerResponse } | { remove: ReadonlySet<string> };

function applyBaselineRegistration(
  baseline: MapLayerResponse[],
  registration: BaselineRegistration,
): MapLayerResponse[] {
  if ('add' in registration) {
    const layer = registration.add;
    return baseline.some((l) => l.id === layer.id) ? baseline : [...baseline, { ...layer }];
  }
  return baseline.filter((l) => !registration.remove.has(l.id));
}

/**
 * Pair each sent layer that a full replacement stored under a new id with its
 * new row. The PUT keeps a listed id the map still has and creates a row for
 * one it doesn't, such as a layer deleted while the PUT was in flight. Rows
 * created during the save are never paired; sent layers and new rows of the
 * same dataset pair in stack order.
 */
function pairReplacedLayerIds(
  sent: readonly MapLayerResponse[],
  stored: readonly MapLayerResponse[],
  createdIds: ReadonlySet<string>,
  pairable: ReadonlySet<string> | null,
  existingIds: ReadonlySet<string>,
): Map<string, string> {
  const sentIds = new Set(sent.map((layer) => layer.id));
  const storedIds = new Set(stored.map((layer) => layer.id));
  const newRowsByDataset = new Map<string, string[]>();
  for (const row of stored) {
    if (sentIds.has(row.id) || createdIds.has(row.id) || existingIds.has(row.id)) continue;
    const queue = newRowsByDataset.get(row.dataset_id);
    if (queue) queue.push(row.id);
    else newRowsByDataset.set(row.dataset_id, [row.id]);
  }
  const pairs = new Map<string, string>();
  for (const layer of sent) {
    if (storedIds.has(layer.id) || (pairable && !pairable.has(layer.id))) continue;
    const next = newRowsByDataset.get(layer.dataset_id)?.shift();
    if (next) pairs.set(layer.id, next);
  }
  return pairs;
}

/**
 * The save-diff baseline after a full replacement: what the server stored of
 * this save's layers. The PUT deletes layers created while it was in flight
 * and recreates layers deleted meanwhile under new ids, so the next save sends
 * those creates again and removes the recreated rows. A create recorded before
 * `stored` was read and missing from it is left out of the baseline: sending
 * it again is safer than losing it. Registrations from `readFrom` on landed
 * after the read, so they are replayed. `renamed` maps each sent layer the
 * server stored under a new id to that id; `pairable`, when given, limits that
 * pairing to the layers a PATCH added, and rows in `existingIds`, which the
 * map held before the save, are never paired.
 */
function replacedBaseline(
  sent: readonly MapLayerResponse[],
  stored: MapLayerResponse[],
  registrations: readonly BaselineRegistration[],
  readFrom: number,
  pairable: ReadonlySet<string> | null,
  existingIds: ReadonlySet<string>,
): { renamed: Map<string, string>; baseline: MapLayerResponse[] } {
  const createdIds = new Set<string>();
  for (const r of registrations) if ('add' in r) createdIds.add(r.add.id);
  const renamed = pairReplacedLayerIds(sent, stored, createdIds, pairable, existingIds);
  // Rows another session added aren't in the local stack, so a baseline that
  // held them would make the next save delete them. A sent layer it deleted
  // stays in the baseline, so the next save doesn't create it again.
  const known = new Set([...sent.map((l) => l.id), ...renamed.values(), ...createdIds]);
  const storedIds = new Set(stored.map((l) => l.id));
  const deletedElsewhere = sent.filter((l) => !storedIds.has(l.id) && !renamed.has(l.id));
  return {
    renamed,
    // A DELETE that committed after the read-back isn't in `stored`.
    baseline: registrations
      .filter((r, i) => 'remove' in r || i >= readFrom)
      .reduce(applyBaselineRegistration, [
        ...hydrateFolderGroupLayers(stored.filter((l) => known.has(l.id))).layers,
        ...deletedElsewhere,
      ]),
  };
}

/** ``payload`` with its dashboard widgets pointed at the ids ``renamed`` gives their layers. */
function withRenamedWidgetLayers(
  payload: MapUpdateRequest,
  renamed: ReadonlyMap<string, string>,
): MapUpdateRequest {
  const config = payload.dashboard_config;
  if (!config?.widgets || renamed.size === 0) return payload;
  return {
    ...payload,
    dashboard_config: {
      ...config,
      widgets: config.widgets.map((w) => {
        const next = 'layer_id' in w && renamed.get(w.layer_id);
        return next ? { ...w, layer_id: next } : w;
      }),
    },
  };
}

export function buildLayerDiff(
  baselineLayers: MapLayerResponse[],
  currentLayers: MapLayerResponse[],
  groupMeta: Record<string, FolderGroupMeta> = {},
): LayerDiffResult {
  // Prepare both sides through prepareLayersForPersistence so an unchanged
  // grouped map diffs empty. The baseline is prepared with its own persisted
  // collapse state (from the folderGroupExpanded markers it was loaded with),
  // not the live groupMeta: stamping the live value on both sides would hide
  // collapse changes from the diff.
  const baselineGroupMeta: Record<string, FolderGroupMeta> = {};
  for (const layer of baselineLayers) {
    const persisted = getPersistedFolderGroup(layer);
    if (persisted?.expanded !== undefined) {
      baselineGroupMeta[persisted.id] = { expanded: persisted.expanded };
    }
  }
  const baselinePersistedLayers = prepareLayersForPersistence(baselineLayers, baselineGroupMeta);
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
    // prepareLayersForPersistence writes folder-group markers into
    // style_config for every layer type, so a baseline that carried them makes
    // a null-out an intentional clear (ungrouping), not a "field never
    // populated" artifact. Otherwise ungrouping a raster layer would never
    // PATCH (its empty style_config compacts to null) and the group would
    // resurrect on reload.
    const baselineHadFolderGroup =
      getPersistedFolderGroup({ style_config: baseline.style_config } as MapLayerResponse) !== null;
    const currentSnapshot = toLayerSnapshot(layer);
    const patch: MapLayerPatch = { id: layer.id };
    for (const field of PATCHABLE_LAYER_FIELDS) {
      const currentValue = currentSnapshot[field];
      const baselineValue = baseline[field];
      if (stableJson(currentValue) === stableJson(baselineValue)) continue;

      // Never emit an explicit null-out for a nullable field this layer's type
      // has no editor for: omit the key (the server keeps what it has) instead
      // of nulling real data. A new non-null value still patches through.
      // style_config is exempt when the baseline carried folder-group markers,
      // since that null is a deliberate erasure.
      if (
        currentValue == null &&
        unmanaged.has(field) &&
        !(field === 'style_config' && baselineHadFolderGroup)
      ) continue;

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
  /** Custom map-level legend title. Null = no override. */
  legendTitle: string | null;
  /** Whether readers can open the Map data table. */
  showAttributeTable?: boolean;
  dockNotes: string;
  /** The Builder's dashboard; a save sends it only when `dashboardEdited`. */
  dashboard: DashboardDraft;
  savedDashboard: DashboardDraft;
  dashboardEdited: boolean;
  /**
   * Told what a save sends, so the saved dashboard coming back isn't taken for
   * another editor's; the returned callback hears whether the server stored it.
   */
  onDashboardSave?: (draft: DashboardDraft) => (stored: boolean) => void;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
  /** Unsaved changes other than a camera-only move; these ask before leaving. */
  hasUnsavedEdits: boolean;
  hasThumbnail?: boolean;
  /** Callback ref populated by useBuilderSave and invoked by useBuilderLayers'
   *  layer-create paths (handleAddDataset / handleDuplicateRendering) so the
   *  server-created layer is registered into the save-diff baseline when
   *  inserted. `remove` is the delete half, called by the single and bulk
   *  delete paths alongside their savedLayerBaselineRef prune. */
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>;
  /** Renames local layers (old id to new id) after a full-replacement save
   *  stored them under new ids. */
  remapLayerIds: (ids: ReadonlyMap<string, string>) => void;
  /** useBuilderLayers' save fence: begun when the round trip starts, settled
   *  when it ends. */
  saveFence: SaveFence;
  /** True when the builder was opened with a ?add_dataset URL param, so the
   *  first auto-capture is deferred until the layer-add effect has synced
   *  localLayers. */
  pendingLayerAdd?: boolean;
}

const DASHBOARD_SAVE_ERRORS = new Set([
  'errors.dashboardTooNew',
  'errors.dashboardTooManyWidgets',
  'errors.dashboardWidgetsRefused',
]);

/** The state fields handleSave snapshots into its payloads. If any changes
 *  identity while the save's network round-trip is in flight, the dirty flag
 *  must survive: clearing it would absorb the mid-save edit into the baseline
 *  and let the query-invalidation resync overwrite it on screen. */
const SAVE_SNAPSHOT_FIELDS = [
  'localLayers',
  'groupMeta',
  'localName',
  'localDescription',
  'legendTitle',
  'showAttributeTable',
  'dockNotes',
  'dashboard',
  'localBasemap',
  'showBasemapLabels',
  'basemapConfig',
  'terrainConfig',
] as const satisfies readonly (keyof SaveState)[];

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
      // Stamp the live groupMeta expansion into the snapshot's persisted
      // markers. After a save clears the dirty flag, localLayers' markers still
      // carry the loaded collapse state, so a verbatim copy would hide the
      // just-saved collapse from the next diff.
      baselineLayersRef.current = stampPersistedFolderGroupExpanded(
        state.localLayers,
        state.groupMeta,
      );
    }
  }, [state.hasUnsavedChanges, state.localLayers, state.groupMeta]);

  // handleSave destructures `state` once and then awaits the network; this ref
  // points at the latest rendered state so post-await code can tell whether
  // anything was edited meanwhile. Assigned during render, not in an effect:
  // effects run after paint, so a mutation resolving as an edit commits could
  // read a stale ref and clear the dirty flag anyway.
  const latestStateRef = useRef(state);
  latestStateRef.current = state;
  const captureIsStale = useCallback(
    (mapId: string) =>
      latestStateRef.current.hasUnsavedChanges || latestStateRef.current.mapId !== mapId,
    [],
  );

  function editedDuringSave(
    sent: SaveState,
    sentPluginSet: ReadonlySet<string>,
    sentCamera: BuilderCamera,
  ): boolean {
    const latest = latestStateRef.current;
    // The camera is read off the map, not SaveState, so a pan during the round
    // trip changes none of the fields below. Any view on screen other than
    // sentCamera is unsaved; clearing the flag would hide it until a refetch
    // that may fail.
    if (!sameMapCamera(sentCamera, readMapCamera(latest.mapInstanceRef.current))) return true;
    // The plugins payload reads usePluginStore, not SaveState, so compare the
    // store's Set identity too (every toggle produces a new Set).
    if (usePluginStore.getState().activePlugins !== sentPluginSet) return true;
    return SAVE_SNAPSHOT_FIELDS.some((field) => sent[field] !== latest[field]);
  }

  // A save's sent snapshot predates layers created or deleted while it is in
  // flight, so each save logs those registrations and replays them when the
  // baseline advances to its snapshot.
  const inFlightRegistrationsRef = useRef(new Set<BaselineRegistration[]>());
  const { saveBaselineSyncRef } = state;
  useEffect(() => {
    const register = (registration: BaselineRegistration) => {
      baselineLayersRef.current = applyBaselineRegistration(baselineLayersRef.current, registration);
      for (const log of inFlightRegistrationsRef.current) log.push(registration);
    };
    // Let layer-create paths register the server-created layer into the
    // save-diff baseline. Otherwise a dirty map inserted with a POST-created
    // layer leaves the baseline unaware of the new server id, buildLayerDiff
    // reports it as added and the PATCH creates a duplicate. The pure server
    // layer is registered (no local grouping/reorder) so those still diff.
    saveBaselineSyncRef.current = {
      add: (layer: MapLayerResponse) => register({ add: layer }),
      // The mirror of `add`. The baseline effect above refreshes only while the
      // map is clean, so a delete on a dirty map would leave the deleted ids
      // in the baseline, the next save would emit them in diff.removed and the
      // backend would reject the whole diff.
      remove: (layerIds: Iterable<string>) => {
        const ids = new Set(layerIds);
        if (ids.size === 0) return;
        register({ remove: ids });
      },
    };
  });

  async function handleSave() {
    const {
      mapId: id,
      mapInstanceRef,
      localName,
      localDescription,
      legendTitle,
      showAttributeTable,
      dockNotes,
      dashboard,
      savedDashboard,
      dashboardEdited: sendDashboard,
      localBasemap,
      localLayers,
      groupMeta = {},
      showBasemapLabels,
      basemapConfig,
      terrainConfig,
      saveFence,
    } = state;
    // Overlapping saves can land out of order and let the older snapshot win.
    if (!id || saveFence.inFlight(id)) return;
    setLastSaveFailed(false);
    // The plugin set the payload below serializes, so the post-await
    // comparison can detect a mid-save toggle.
    const sentPluginSet = usePluginStore.getState().activePlugins;

    // Block save if a layer's popup expression references unknown columns.
    // Server-side validation is shape-only, so this is the UX gate.
    const invalidLayer = localLayers.find((l) => {
      const cfg = l.popup_config;
      if (!cfg?.enabled || !cfg.expression) return false;
      // Skip when column metadata is absent; the server is authoritative.
      if (!l.dataset_column_info) return false;
      const columns = l.dataset_column_info.map((c) => c.name);
      return !validatePlaceholders(extractPlaceholders(cfg.expression), columns).ok;
    });
    if (invalidLayer) {
      const layerName = invalidLayer.display_name ?? t('toasts.layerFallbackName');
      toast.error(t('toasts.popupConfigInvalidNamed', { layerName }), { id: 'popup-config-invalid', duration: 6000 });
      return;
    }
    const widgetIssue = sendDashboard ? firstWidgetProblem(dashboard, localLayers) : null;
    if (widgetIssue) {
      toast.error(
        widgetIssue.kind === 'viewWithoutGeometry'
          ? t('toasts.dashboardViewWithoutGeometry')
          : t('toasts.dashboardWidgetInvalid', { column: widgetIssue.column }),
        { id: 'dashboard-widget-invalid', duration: 6000 },
      );
      return;
    }

    const map = mapInstanceRef.current;
    // The persisted camera goes through the normalizer the builder's dirty
    // check also reads, so a pan that would change the stored view is exactly
    // the pan that marks the map unsaved.
    const camera = readMapCamera(map);
    const registrations: BaselineRegistration[] = [];
    // Rows the map held before this save, as last read; none is a row it creates.
    const existingIds = new Set(
      (queryClient.getQueryData<MapResponse>(queryKeys.maps.detail(id))?.layers ?? []).map((l) => l.id),
    );
    let replacedLayers: MapLayerResponse[] | null = null;
    let replacedReadFrom = 0;
    // The layers a PATCH added, the only ones it stored under new ids.
    let patchedAdds: ReadonlySet<string> | null = null;
    // Layers the server stored under new ids, which the metadata PUT's
    // dashboard must name.
    let layerRenames: ReadonlyMap<string, string> = new Map();
    // A layer PATCH commits even when the metadata PUT after it fails, so the
    // baseline advances as soon as it lands; otherwise the retry re-sends
    // removals the server already applied. Layers created or deleted while the
    // save was in flight are replayed onto the sent layers.
    const commitLayerBaseline = () => {
      // The hooks stay mounted across a map switch, so the baseline may
      // belong to another map by now.
      if (latestStateRef.current.mapId !== id) return;
      if (replacedLayers) {
        const { renamed, baseline } = replacedBaseline(
          persistableLayers,
          replacedLayers,
          registrations,
          replacedReadFrom,
          patchedAdds,
          existingIds,
        );
        layerRenames = renamed;
        // The latest render's, whose dashboard draft holds edits made since.
        if (renamed.size > 0) latestStateRef.current.remapLayerIds(renamed);
        baselineLayersRef.current = baseline;
        return;
      }
      baselineLayersRef.current = registrations.reduce(
        applyBaselineRegistration,
        // The save-diff baseline carries the sent collapse state (see the
        // baseline effect).
        stampPersistedFolderGroupExpanded(localLayers, groupMeta),
      );
    };
    // useUpdateMap only invalidates the detail query, so mapData keeps the
    // pre-save camera until the refetch lands (and forever if it fails). The
    // dirty check reads mapData, so publish what the server holds.
    const commitSaved = () => {
      queryClient.setQueryData<MapResponse>(
        queryKeys.maps.detail(id),
        (prev) => (prev ? { ...prev, ...camera } : prev),
      );
      commitLayerBaseline();
    };

    // basemap_position is a field of basemapConfig (MapBasemapConfig jsonb), so
    // it round-trips through the wholesale basemap_config pass-through below.
    // Legacy maps load it undefined and default to 'bottom' on the read path.
    const metadataPayload: MapUpdateRequest = {
      name: localName || undefined,
      description: localDescription.trim() || null,
      notes: dockNotes.trim() || null,
      basemap_style: localBasemap,
      show_basemap_labels: showBasemapLabels,
      basemap_config: basemapConfig,
      terrain_config: terrainConfig,
      center_lng: camera.center_lng,
      center_lat: camera.center_lat,
      zoom: camera.zoom,
      bearing: camera.bearing,
      pitch: camera.pitch,
      plugins: resolvePluginsPayload(id, queryClient, enabledPluginIds),
      // Empty/null clears the custom legend title server-side.
      legend_title: legendTitle && legendTitle.trim() ? legendTitle.trim() : null,
      ...(showAttributeTable === undefined ? {} : { show_attribute_table: showAttributeTable }),
      ...(sendDashboard
        ? { dashboard_config: dashboardPayload(dashboard, localLayers, savedDashboard.panel) }
        : {}),
    };
    const persistableLayers = prepareLayersForPersistence(localLayers, groupMeta);
    const fullReplacementPayload: MapUpdateRequest = {
      ...metadataPayload,
      layers: persistableLayers.map(toLayerInput),
    };

    const settleDashboard = sendDashboard
      ? state.onDashboardSave?.(canonicalDashboard(dashboard, localLayers))
      : undefined;
    // Set once a PUT carrying the dashboard succeeds; every PUT below does.
    let dashboardStored = false;
    const putMap = async (data: MapUpdateRequest) => {
      const saved = await updateMap.mutateAsync({ id, data });
      dashboardStored = true;
      return saved;
    };
    const replaceLayers = async () => {
      const saved = await putMap(fullReplacementPayload);
      replacedReadFrom = registrations.length;
      try {
        // Joins the detail refetch the PUT started, if one is running. Unlike
        // the PUT response, it includes creates and deletes that landed after
        // the PUT.
        const stored = await queryClient.fetchQuery({ ...mapDetailQuery(id), staleTime: 0 });
        replacedLayers = stored.layers ?? [];
      } catch {
        replacedLayers = saved.layers ?? [];
      }
    };
    // The server stores added layers under new ids, so reconcile from a
    // PATCH's rows as after a replacement. A PATCH deletes nothing it doesn't
    // name, so every create made during the save is kept.
    const adoptPatched = (layerDiff: MapLayerDiffRequest, patched: MapResponse) => {
      if (!layerDiff.added?.length) return;
      replacedLayers = patched.layers ?? [];
      replacedReadFrom = 0;
      patchedAdds = new Set(layerDiff.added.flatMap((l) => (l.id ? [l.id] : [])));
    };
    saveFence.begin(id);
    inFlightRegistrationsRef.current.add(registrations);
    try {
      const { diff, unsupported } = buildLayerDiff(baselineLayersRef.current, localLayers, groupMeta);
      // The DEM hillshade overlay (style_config.render_mode) and the 3D terrain
      // binding (terrain_config) are independent authorities. A save that
      // persists only one (layer PATCH commits, metadata PUT fails) is an
      // incomplete save of two independent settings, coherent on reload and
      // recoverable by re-toggling, so the split PATCH+PUT path is safe. That
      // avoids forcing every combined save through the lossy full-replacement
      // PUT (see below). The failed-save toast prompts a retry.
      if (unsupported) {
        await replaceLayers();
      } else {
        if (hasDiff(diff)) {
          try {
            adoptPatched(diff, await patchMapLayers.mutateAsync({ id, diff }));
            commitLayerBaseline();
          } catch (error) {
            // A stale diff is a conflict, not a missing endpoint. Refetch, drop
            // the ids the server no longer has, and retry the PATCH. A failure
            // here goes to the outer catch with a dedicated message and must
            // never reach the full PUT below.
            if (isStaleLayerDiffError(error)) {
              try {
                const fresh = await getMap(id);
                // GET /maps/{id} orders layers by sort_order: the server's
                // current sequence, which the order merge needs.
                const serverLayerIds = (fresh.layers ?? []).map((l) => l.id);
                const reconciled = reconcileLayerDiffWithServer(diff, serverLayerIds);
                if (hasDiff(reconciled)) {
                  adoptPatched(reconciled, await patchMapLayers.mutateAsync({ id, diff: reconciled }));
                }
              } catch {
                throw new StaleLayerDiffError();
              }
              commitLayerBaseline();
              await putMap(withRenamedWidgetLayers(metadataPayload, layerRenames));
              commitSaved();
              toast.warning(t('toasts.mapSavedAfterRemoteChange'));
              if (!editedDuringSave(state, sentPluginSet, camera)) {
                state.setHasUnsavedChanges(false);
              }
              if (map && id) captureThumbnail(map, id, queryClient, localLayers, undefined, undefined, 'save', captureIsStale);
              return;
            }
            if (!isUnsupportedLayerPatchError(error)) throw error;
            // Falling back from a rejected partial PATCH to a full PUT
            // re-serializes every layer via toLayerInput (a lossy
            // style_config/paint round-trip, fresh layer-row UUIDs). It is
            // surfaced to the user rather than reported as a plain "Map saved",
            // so they double-check layer styling.
            await replaceLayers();
            commitSaved();
            toast.warning(t('toasts.mapSavedFullResync', {
              defaultValue: 'Map saved, but required a full re-sync. Please double-check layer styling.',
            }));
            // Clear the dirty flag only when nothing was edited during the await.
            if (!editedDuringSave(state, sentPluginSet, camera)) {
              state.setHasUnsavedChanges(false);
            }
            if (map && id) captureThumbnail(map, id, queryClient, localLayers, undefined, undefined, 'save', captureIsStale);
            return;
          }
        }
        await putMap(withRenamedWidgetLayers(metadataPayload, layerRenames));
      }

      commitSaved();
      toast.success(t('toasts.mapSaved'));
      // The baseline is the sent snapshot; clear the dirty flag only when
      // nothing was edited during the await, or the baseline effect would
      // absorb the mid-save edit and the invalidation resync would overwrite
      // it on screen.
      if (!editedDuringSave(state, sentPluginSet, camera)) {
        state.setHasUnsavedChanges(false);
      }

      // Fire-and-forget thumbnail upload. Use `map` captured before mutate:
      // mapInstanceRef.current may be transiently null during re-render.
      if (map && id) {
        captureThumbnail(map, id, queryClient, localLayers, undefined, undefined, 'save', captureIsStale);
      }
    } catch (err) {
      setLastSaveFailed(true);
      // The layers changed in another session and the diff could not be
      // reconciled. Say so rather than report a generic failure or overwrite
      // the map with this session's stale snapshot.
      if (err instanceof StaleLayerDiffError) {
        toast.error(t('toasts.saveConflictReload'));
        return;
      }
      // Surface a FastAPI 422 popup_config rejection as a structured toast.
      // err.body is the raw detail (an array of {loc, msg, type} for validation
      // errors); any unexpected shape falls through to the generic saveFailed.
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
      // A dashboard the server refused says why; the error already carries the localized reason.
      if (err instanceof ApiError && DASHBOARD_SAVE_ERRORS.has(classifyApiError(err.body, err.status).key)) {
        toast.error(err.message);
        return;
      }
      toast.error(t('toasts.saveFailed'));
    } finally {
      settleDashboard?.(dashboardStored);
      inFlightRegistrationsRef.current.delete(registrations);
      saveFence.settle(id);
    }
  }

  function handleExportPNG() {
    const map = state.mapInstanceRef.current;
    if (!map) return;

    const doExport = () => {
      // Force a render frame, then composite chrome (title, legend, branding)
      // onto an offscreen canvas. The WebGL canvas doesn't retain its drawing
      // buffer, so the read is registered on the next render event.
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

          const legendRows = state.localLayers.flatMap((layer) => {
            if (!layer.visible || layer.show_in_legend === false) return [];
            const facts = legendFacts(layer);
            return facts ? [{ layer, facts }] : [];
          });
          const terrainEntry = syntheticTerrainEntry(
            state.terrainConfig,
            state.localLayers,
            legendRows.map(({ layer }) => layer),
            { labelKey: 'plugins.legend.terrain3d' },
          );
          const legendRowCount = legendRows.length + (terrainEntry ? 1 : 0);
          const legendHeaderH = legendRowCount > 0 ? 32 * dpr : 0;
          const legendRowH = 22 * dpr;
          const legendBlockH =
            legendRowCount > 0
              ? 12 * dpr + legendHeaderH + legendRowCount * legendRowH + 12 * dpr
              : 0;

          const showBranding = !isEnterprise;
          const footerH = showBranding ? 32 * dpr : 0;

          const totalW = Math.round(mapWidth);

          const off = document.createElement('canvas');
          off.width = totalW;
          const ctx = off.getContext('2d');
          if (!ctx) {
            toast.error(t('toasts.exportFailed'));
            return;
          }

          // The attribution band is measured before the canvas is sized, since
          // its height feeds totalH. It measures on this context rather than a
          // scratch canvas: `off` has its width but not yet its height, and
          // setting the height resets context state.
          //
          // Not gated on showBranding: "Powered by GeoLens" is promotion an
          // enterprise licence may suppress, but a basemap or dataset credit is
          // a licensing obligation and is always drawn.
          //
          // The band is the only elastic term in totalH, so it gets the height
          // a browser will still encode, less what the fixed blocks spent.
          // Unbounded, a contract-maximum map (200 layers x 5,000 characters of
          // credit) asked for a canvas past engine limits and `toBlob` returned
          // null.
          const reservedH = titleBlockH + mapHeight + legendBlockH + footerH;
          const attributionBand = measureAttributionBand(
            ctx,
            readRenderedAttribution(map),
            {
              maxWidth: totalW - pad * 2,
              dpr,
              maxHeight: attributionBandHeightBudget(totalW, reservedH),
            },
          );

          const totalH = Math.round(reservedH + attributionBand.height);
          off.height = totalH;

          ctx.fillStyle = MAP_COLORS.exportImage.background;
          ctx.fillRect(0, 0, totalW, totalH);

          let cursorY = 0;
          ctx.textBaseline = 'top';

          if (title) {
            ctx.fillStyle = MAP_COLORS.exportImage.text;
            ctx.font = `700 ${titleFontPx}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            ctx.fillText(title, pad, cursorY + pad);
            if (description) {
              ctx.fillStyle = MAP_COLORS.exportImage.mutedText;
              ctx.font = `400 ${descFontPx}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
              ctx.fillText(description, pad, cursorY + pad + titleFontPx + 8 * dpr);
            }
            cursorY += titleBlockH;
          }

          // Only the map band gets the space color under the canvas: the globe's
          // void is transparent and would export as a sphere on white. The
          // title/legend/footer bands stay white (their text is #0a0a0a).
          if (hasGlobeSpaceBackdrop(map)) {
            ctx.fillStyle = MAP_COLORS.exportImage.globeBackground;
            ctx.fillRect(0, cursorY, totalW, mapHeight);
          }
          ctx.drawImage(srcCanvas, 0, cursorY);
          cursorY += mapHeight;

          if (legendRowCount > 0) {
            cursorY += 12 * dpr;
            ctx.fillStyle = MAP_COLORS.exportImage.text;
            ctx.font = `600 ${14 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            // Honor the custom legend title like the on-screen legend; fall
            // back to the localized default header.
            const legendHeaderText = state.legendTitle?.trim()
              ? state.legendTitle.trim()
              : t('export.legendHeader', { defaultValue: 'Legend' });
            ctx.fillText(legendHeaderText, pad, cursorY);
            cursorY += legendHeaderH;
            const rowFont = `400 ${13 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            ctx.font = rowFont;
            const swatchSize = 14 * dpr;
            if (terrainEntry) {
              // The builder legend pins this row first and draws its icon as the
              // raster glyph chip.
              const rowY = cursorY + (legendRowH - swatchSize) / 2;
              const glyph = demChipGlyph('terrain');
              const glyphPx = 11 * dpr;
              ctx.fillStyle = MAP_COLORS.exportImage.rasterChip.background;
              ctx.fillRect(pad, rowY, swatchSize, swatchSize);
              ctx.font = `600 ${glyphPx}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
              ctx.fillStyle = MAP_COLORS.exportImage.rasterChip.glyph;
              ctx.fillText(
                glyph,
                pad + (swatchSize - ctx.measureText(glyph).width) / 2,
                rowY + (swatchSize - glyphPx) / 2,
              );
              ctx.font = rowFont;
              ctx.fillStyle = MAP_COLORS.exportImage.text;
              ctx.fillText(
                terrainEntry.sourceName ?? t(terrainEntry.labelKey),
                pad + swatchSize + 10 * dpr,
                cursorY + (legendRowH - 13 * dpr) / 2,
              );
              cursorY += legendRowH;
            }
            for (const { facts } of legendRows) {
              // Mirror the on-screen swatch: a gradient for multi-stop ramps, and the
              // stroke the map draws as the border, so a hollow circle (light fill,
              // coloured ring) doesn't export blank.
              const { swatch } = facts;
              const colors = getLayerColors(facts);
              const rowY = cursorY + (legendRowH - swatchSize) / 2;
              const solidFill = colors.find((c) => !!c) || MAP_COLORS.icon.fallback;
              let filled = false;
              if (colors.length > 1) {
                try {
                  const grad = ctx.createLinearGradient(pad, 0, pad + swatchSize, 0);
                  const stops = facts.ramp
                    ? rampGradient(facts.ramp)
                    : colors.map((color, i) => ({ color, offset: i / (colors.length - 1) }));
                  stops.forEach(({ color, offset }) => grad.addColorStop(offset, color));
                  ctx.fillStyle = grad;
                  filled = true;
                } catch {
                  // An unparseable ramp color makes addColorStop throw; fall back to a
                  // solid swatch rather than aborting the whole export.
                }
              }
              if (!filled) ctx.fillStyle = solidFill;
              const layerAlpha = swatch?.opacity ?? 1;
              ctx.globalAlpha = layerAlpha * (swatch?.fillOpacity ?? 1);
              ctx.fillRect(pad, rowY, swatchSize, swatchSize);
              ctx.globalAlpha = layerAlpha;
              ctx.strokeStyle = swatch?.stroke?.color ?? MAP_COLORS.previewOutline;
              ctx.lineWidth = Math.max(1, dpr);
              ctx.strokeRect(pad, rowY, swatchSize, swatchSize);
              ctx.globalAlpha = 1;
              ctx.fillStyle = MAP_COLORS.exportImage.text;
              ctx.fillText(
                facts.name,
                pad + swatchSize + 10 * dpr,
                cursorY + (legendRowH - 13 * dpr) / 2,
              );
              cursorY += legendRowH;
            }
          }

          // Between the legend and the branding footer, on white rather than
          // over imagery, so no scrim and no credit is dropped for want of room
          // (it wraps instead).
          //
          // Positioned off the block heights, not `cursorY`: the legend loop
          // leaves the cursor 12*dpr above its block bottom (it never adds
          // legendBlockH's trailing pad), so following it would draw the band
          // into the legend's padding and leave 12*dpr of dead white at the foot.
          drawAttributionBand(ctx, attributionBand, {
            x: pad,
            y: titleBlockH + mapHeight + legendBlockH,
            dpr,
          });

          if (showBranding) {
            const footerText = t('export.poweredBy', { defaultValue: 'Powered by GeoLens' });
            ctx.fillStyle = MAP_COLORS.exportImage.branding;
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

  // Auto-capture a thumbnail on first map load if none exists, called from
  // handleMapRef when the map instance becomes available. Memoized to keep the
  // callback ref identity stable and avoid transient null ref cycles.
  const thumbCaptured = useRef(false);
  const captureSignalRef = useRef<{ cancelled: boolean }>({ cancelled: false });
  const localLayersRef = useRef(state.localLayers);
  localLayersRef.current = state.localLayers;

  const maybeAutoCaptureThumbnail = useCallback((map: MaplibreMap) => {
    if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
    // The per-instance `thumbCaptured` ref doesn't survive a Vite-dev
    // StrictMode unmount/remount, so a second hook instance for the same mapId
    // can re-enter with a fresh ref. The module-level `shouldAutoCapture`
    // guard owns the "already initiated for this mapId this session" invariant,
    // keyed per user so an auth switch doesn't inherit the previous entry.
    const userId = useAuthStore.getState().user?.id ?? null;
    if (!shouldAutoCapture(state.mapId, userId)) {
      thumbCaptured.current = true; // keep the instance ref consistent
      return;
    }
    thumbCaptured.current = true;
    captureSignalRef.current = { cancelled: false };
    // When a layer-add is pending (new-map + ?add_dataset), pass the live
    // localLayersRef so runCaptureNow defers until layers arrive.
    const layersRef = state.pendingLayerAdd ? localLayersRef : undefined;
    captureThumbnail(map, state.mapId, queryClient, localLayersRef.current, captureSignalRef.current, layersRef, 'auto', captureIsStale);
  }, [state.hasThumbnail, state.mapId, state.pendingLayerAdd, queryClient, captureIsStale]);

  // Cancel in-flight polling on unmount
  useEffect(() => {
    return () => { captureSignalRef.current.cancelled = true; };
  }, []);

  // Warn before tab close / refresh with unsaved edits, and block in-app navigation
  const blocker = useUnsavedGuard(state.hasUnsavedEdits);

  // Keyboard shortcut: Ctrl/Cmd+S
  const handleSaveRef = useRef(handleSave);
  handleSaveRef.current = handleSave;
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        // preventDefault fires unconditionally to suppress the browser "Save
        // Page As" dialog, regardless of pending state or open modals.
        e.preventDefault();
        // No-op when a Radix dialog/sheet is open, so Cmd+S inside the Share
        // dialog or Add Dataset modal doesn't race a layer mutation against
        // open-modal context. The role-dialog selector covers Dialog and Sheet.
        // AlertDialog content renders role="alertdialog" and is matched
        // explicitly so the unsaved-changes leave dialog still suppresses
        // Cmd+S. The builder's inline row confirms also use role="alertdialog"
        // but have no data-state attribute, so they intentionally don't match.
        const dialogOpen = document.querySelector(
          '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]',
        );
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
