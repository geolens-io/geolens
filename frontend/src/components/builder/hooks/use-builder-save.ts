import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getSourceIdForLayer } from '@/components/builder/map-sync';
import { hasGlobeSpaceBackdrop } from '@/components/builder/map-composition-sync';
import { ApiError } from '@/api/client';
import { useUpdateMap, useDuplicateMap, usePatchMapLayers } from '@/hooks/use-maps';
import { useEnabledPlugins } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import { getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import { getMap, uploadThumbnail, uploadOgImage } from '@/api/maps';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { MapBasemapConfig, MapLayerDiffRequest, MapLayerInput, MapLayerPatch, MapLayerResponse, MapResponse, MapTerrainConfig, MapUpdateRequest } from '@/types/api';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useAuthStore } from '@/stores/auth-store';
import { getDefaultPluginIds, resolveAvailablePluginIds, samePluginIds } from '@/components/map-plugins';
// D5: the PNG export legend must render the same effective entry names as the
// on-screen legend (per-entry legendLabel override > display name > dataset name).
import { legendEntryName } from '@/components/map-plugins/builtin/LegendPlugin';
import { getPersistedFolderGroup, prepareLayersForPersistence, stampPersistedFolderGroupExpanded, type FolderGroupMeta } from '@/components/builder/folder-groups';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import { MAP_COLORS } from '@/lib/map-colors';
// feat(#1486): the three rendered-image paths all composite from the WebGL
// canvas, which no DOM attribution control can reach. See lib/map-image-attribution.
import {
  attributionBandHeightBudget,
  drawAttributionBand,
  drawAttributionOverlay,
  measureAttributionBand,
  readRenderedAttribution,
  OG_ATTRIBUTION,
  THUMBNAIL_ATTRIBUTION,
} from '@/lib/map-image-attribution';
// fix(#430 V-01): capability gate used to detect fields the builder has no editor
// for on a given layer type (see unmanagedNullableFields below).
import { getLayerCapabilities, isFolderGroupLayer } from '@/lib/layer-capabilities';

/** Center-crop `srcCanvas` to the given target dimensions and return the
 *  resulting offscreen canvas. Crops from the center without distortion
 *  (letterbox / pillarbox math). Supports any target aspect ratio.
 *
 *  SHARE-08 (Phase 1142): extracted from the former inline doCapture crop block
 *  to allow two crops (400×250 thumbnail, 1200×630 OG image) to share one
 *  render event with a single triggerRepaint().
 *
 *  fix(#1479 Codex P2 round 1): `backdrop` is painted under the crop when the
 *  globe space backdrop is on screen. The WebGL canvas is transparent wherever
 *  a ray missed the planet, so without it the sphere lands on whatever the
 *  encoder substitutes for alpha — white once composited, black for JPEG,
 *  neither of them the space color the map is actually showing. */
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

/** fix(#1502): channel stddev below this reads as "no content". The demo's
 *  two blank uploads measured 0.00 and 1.88; the flattest REAL thumbnail
 *  observed on a seeded instance measured 22.9, and even a bare world-basemap
 *  capture measures ~24 (all measured as luminance on grey-dominated frames,
 *  where per-channel and luminance stddev coincide, so the thresholds carry
 *  over). The gap is wide; 4 sits far from both sides so a legitimately
 *  minimal map (open ocean on a flat basemap) still clears it in practice,
 *  while a frame that never painted cannot. */
export const BLANK_CHANNEL_STDDEV = 4;

/** fix(#1504 review round 2): stddev alone rejects legitimately SPARSE maps —
 *  a lone point feature on the "No basemap" uniform background computes to a
 *  stddev around 2, under the threshold. So a low-variance frame gets a second
 *  chance: count pixels deviating meaningfully from the mean color. The two
 *  demo blank uploads have ZERO such pixels — a smooth gradient at stddev
 *  1.88 spans roughly ±3 — while a real point feature deviates by 100+ across
 *  its whole footprint. 8 pixels is far above stray readback noise and far
 *  below any visible feature's footprint. */
export const SPARSE_CHANNEL_DELTA = 25;
export const SPARSE_PIXEL_COUNT = 8;

/** Max per-channel standard deviation over RGBA data, scanning every pixel
 *  (sampling can miss a dot — #1504 review round 2). Channel-space rather
 *  than luminance (#1504 review round 3): isoluminant hue changes — say a
 *  red/green categorical split at equal lightness — are invisible to a
 *  luminance statistic but enormous per channel. Pure so it is testable
 *  without a canvas (jsdom has none). */
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
 *  EVERY channel AND no cluster of pixels standing off the mean color in any
 *  channel (the sparse-map rescue above). Pure for the same jsdom reason. */
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

/** fix(#1502): whether a captured frame is effectively a solid fill.
 *
 *  The capture pipeline is fail-open at every stage before this point —
 *  waitForVisibleLayerSources proceeds on its 5s deadline, whenMapIdle fires
 *  on its 3s timeout — so on a slow first render doCapture can read a canvas
 *  nothing has painted. Uploading that frame is what makes the failure
 *  PERMANENT: the auto-capture gate is `hasThumbnail`, so one blank upload
 *  disqualifies the map from every future attempt (the demo shipped two such
 *  thumbnails for months).
 *
 *  Reads the already-small thumbnail crop (no extra canvas), and fails open:
 *  if the 2D context or pixel data is unavailable, report "not blank" so the
 *  upload proceeds exactly as before this guard existed. */
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
/** Who asked for this capture. The blank-frame guard applies ONLY to 'auto'
 *  (#1504 review round 4): auto-capture fires on first open, where a uniform
 *  frame means the unpainted-canvas race. On an explicit save the map is
 *  loaded and painted — a uniform frame is the map's true appearance (the
 *  user removed its content), and skipping the upload would leave a stale
 *  thumbnail advertising layers that no longer exist, with `hasThumbnail`
 *  true so no retry ever corrects it. */
type CaptureTrigger = 'auto' | 'save';

/** Whether the ENTIRE source frame reads as unpainted (#1504 review round 5).
 *
 *  The guard's one job is detecting the unpainted-canvas race, and an
 *  unpainted canvas is blank EVERYWHERE — so the honest measurement is the
 *  full frame, once. Judging the two crops individually (an earlier revision)
 *  had a terminal converse: content only in the top/bottom strips makes the
 *  1.6 thumbnail crop real and the wider 1.905 OG crop genuinely uniform, the
 *  thumbnail upload flips `hasThumbnail`, and the skipped-but-truthful OG can
 *  never retry. Once the frame is known painted, every crop is the map's true
 *  appearance at its aspect ratio and must upload.
 *
 *  WebGL pixels are unreadable through 2D APIs on the source itself, so the
 *  frame is copied into a 2D canvas — BOUNDED to ~1M pixels (#1504 review
 *  round 6): a native copy on a DPR-2 2560×1440 display is ~14.7M pixels and
 *  over 110 MiB of transient RGBA inside the render callback, and an
 *  allocation failure would fail open into exactly the blank upload this
 *  guard prevents. The downscale is safe for both classifications: an
 *  unpainted frame is uniform at EVERY scale, and the sparse rescue survives
 *  because drawImage blends rather than drops — an output pixel at just ~13%
 *  feature coverage already crosses the delta-25 deviant threshold, so any
 *  feature of roughly 3×3 effective pixels or larger still rescues. Smaller
 *  than that reads blank, which on auto-capture means skip-and-retry, never a
 *  permanent state. Fail-open, like everything in this pipeline: unreadable
 *  pixels never block uploads. */
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

function doCapture(
  map: MaplibreMap,
  mapId: string,
  queryClient: ReturnType<typeof useQueryClient>,
  trigger: CaptureTrigger,
) {
  const onRender = () => {
    try {
      const srcCanvas = map.getCanvas();
      // fix(#1479 Codex P2 round 1): both crops carry the space backdrop when
      // the map is showing one, so a globe map's thumbnail and OG card match
      // the builder instead of putting the sphere back on a flat background.
      const backdrop = hasGlobeSpaceBackdrop(map)
        ? MAP_COLORS.exportImage.globeBackground
        : undefined;

      // fix(#1502): never persist an unpainted AUTO-captured frame (see
      // CaptureTrigger for why explicit saves are exempt, and
      // isCanvasFrameBlank for why the FULL frame is measured rather than the
      // crops). Skipping leaves `hasThumbnail` false, and re-arming the SF-07
      // guard converts the permanent failure into a transient one within the
      // SPA session, not just across hard reloads (#1504 review round 1) —
      // the next open of the map simply retries.
      if (trigger === 'auto' && isCanvasFrameBlank(srcCanvas)) {
        rearmAutoCapture(mapId);
        if (import.meta.env.DEV) {
          console.warn('[thumbnail] capture skipped: frame is effectively blank; will retry on next open');
        }
        return;
      }

      // feat(#1486): both crops carry the credit line. Read once — the entries
      // are identical for the two targets, only the type size differs — and
      // draw into each finished crop. This has to be a canvas draw: the crops
      // composite from the WebGL canvas, so MapLibre's own DOM attribution
      // control is invisible to them by construction.
      //
      // Deliberately AFTER the blank-frame guard above, which measures
      // srcCanvas: drawing a credit onto the crops must not be able to make an
      // unpainted frame read as painted.
      const credits = readRenderedAttribution(map);

      const thumb = cropResize(srcCanvas, 400, 250, backdrop);
      drawAttributionOverlay(thumb, credits, THUMBNAIL_ATTRIBUTION);
      const og = cropResize(srcCanvas, 1200, 630, backdrop);
      drawAttributionOverlay(og, credits, OG_ATTRIBUTION);

      uploadThumbnail(mapId, thumb.toDataURL('image/jpeg', 0.7)).then(() => {
        // chore(#1021): this refetches nothing on the builder route, and that is
        // expected rather than a bug. maps.all is ['maps'] while the builder mounts
        // useMap, which is ['map', id], a different root string. The target is the
        // MapsPage browse list (['maps', params]), whose MapCard renders
        // thumbnail_url/thumbnail_updated_at: that entry is cached but unmounted
        // while you are in the builder, so marking it stale here is what gets the new
        // thumbnail on screen when the user navigates back. Do not "helpfully" add
        // maps.detail. The builder reads thumbnail_url only as the hasThumbnail
        // auto-capture gate, which shouldAutoCapture's module-level LRU has already
        // settled by the time this upload resolves.
        queryClient.invalidateQueries({ queryKey: queryKeys.maps.all });
      }).catch(() => {
        // Silent failure for thumbnails
      });

      // 1200×630 OG image — fire-and-forget, isolated failure (SHARE-08)
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
  trigger: CaptureTrigger = 'save',
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
        waitForVisibleLayerSources(map, live, () => doCapture(map, mapId, queryClient, trigger), signal);
        return;
      }
      if (Date.now() >= deadline) {
        // SF-05: genuinely empty after the deadline — fall back to idle path so
        // we never leave an open poll. Re-check cancellation INSIDE the idle
        // callback (WR-02): whenMapIdle can fire up to ~3s later, possibly after
        // an unmount, so the guard must be at capture time, not registration time.
        whenMapIdle(map, () => {
          if (!signal?.cancelled) doCapture(map, mapId, queryClient, trigger);
        });
        return;
      }
      setTimeout(pollForLayers, 100);
    };
    pollForLayers();
    return;
  }
  waitForVisibleLayerSources(map, layers, () => doCapture(map, mapId, queryClient, trigger), signal);
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
  trigger: CaptureTrigger = 'save',
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
    runCaptureNow(map, mapId, queryClient, layers, signal, layersRef, trigger);
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
export function shouldAutoCapture(mapId: string, userId: string | null): boolean {
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

/** fix(#1504 review): when doCapture rejects a blank frame, the SF-07 guard
 *  must be re-armed or the promised "retry on next open" only survives a hard
 *  reload — the module LRU outlives unmount/remount within an SPA session.
 *  Keys are `userId:mapId` and doCapture does not know the user, so drop every
 *  entry for the map; any user bucket that re-opens it deserves a fresh try. */
export function rearmAutoCapture(mapId: string): void {
  for (const key of autoCapturedKeys.keys()) {
    if (key.endsWith(`:${mapId}`)) autoCapturedKeys.delete(key);
  }
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

// fix(#1778): only a status that means "this deployment has no layer-diff
// endpoint" may escalate to the lossy full PUT. The old predicate matched
// 400/404/409/422 with a prose regex, which is exactly the shape the backend
// uses for a STALE diff. See isStaleLayerDiffError below.
//
// fix(#1778 codex round 3): 404 is back, because it is the compatibility case
// the PUT fallback exists for. A backend predating PATCH /maps/{id}/layers
// answers 404 for the unknown route (FastAPI sends {"detail": "Not Found"}; an
// edge proxy in front of it may send no JSON at all), and without 404 here
// every layer-edit save against such a deployment would fail outright. 405 and
// 501 are the other route-level answers.
const ROUTE_LEVEL_UNSUPPORTED_STATUSES = new Set([404, 405, 501]);

// The one legitimate 404 the route produces for ITSELF: the map is gone, not
// the route (router.py's "Map not found", and apply_layer_diff's
// "Map {id} not found"). A full PUT would only 404 again, so this surfaces as a
// save failure instead. There is no 404 for a stale LAYER id: apply_layer_diff
// raises ValueError for those and the router maps them to 400, which is what
// isStaleLayerDiffError matches on, by detail and not by status alone.
const MAP_NOT_FOUND_DETAIL = /^Map\b.*\bnot found$/i;

/** The backend detail string, preferring the raw `detail` apiFetch stored on
 *  the error. `message` has already been through translateApiErrorDetail and
 *  may be localized, so it is only a fallback for a non-string detail. */
function apiErrorDetailText(error: ApiError): string {
  return typeof error.body === 'string' ? error.body : error.message;
}

function isUnsupportedLayerPatchError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (!ROUTE_LEVEL_UNSUPPORTED_STATUSES.has(error.status)) return false;
  if (error.status !== 404) return true;
  return !MAP_NOT_FOUND_DETAIL.test(apiErrorDetailText(error));
}

// fix(#1778): the two details apply_layer_diff raises when the diff names layer
// ids the map no longer has (backend service_diff.py). That means someone else
// changed this map's layers since this session loaded it, so overwriting the
// map with the stale client's snapshot would resurrect what they deleted and
// delete what they added. Recover by re-diffing against the server instead.
const STALE_LAYER_DIFF_DETAIL =
  /Layer diff references layer ids outside this map|Layer order references unknown or removed layers/i;

/** fix(#1778): raised when the stale-diff recovery below cannot complete, so
 *  the outer catch can say "the map changed elsewhere" instead of the generic
 *  save-failed message. */
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
 * fix(#1778): drop the parts of a rejected diff the server can no longer apply.
 *
 * Deliberately NOT a fresh `buildLayerDiff` against the refetched map: a layer
 * another session ADDED is absent from this session's `localLayers`, so a full
 * re-diff would emit it as `removed` and delete it. Reconciling the diff we
 * already built keeps the recovery strictly additive to server state: ids the
 * server no longer has are simply dropped, and anything this session did not
 * touch is left alone.
 *
 * `serverLayerIds` is the refetched map's layer SEQUENCE in server sort order,
 * not just a membership set, because the order reconciliation below needs
 * positions.
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
 * fix(#1778 codex round 1): merge this session's relative order into the
 * server's current sequence instead of sending only the ids this session knows.
 *
 * `apply_layer_diff` numbers the ids it is given from 0 and then APPENDS every
 * surviving layer the order omitted. A bare filter would therefore take server
 * order [A, X, B] with local order [B, A], send [B, A], and strand the remotely
 * added X at the end as [B, A, X], moving a layer this session never saw. The
 * stable merge walks the surviving server sequence and substitutes the next
 * locally ordered survivor at each position a locally known layer already
 * occupies, so unseen ids keep their server positions: [B, X, A].
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
    // Every position a locally known survivor occupies is filled from the local
    // sequence, in order. The counts match because localSurvivors is exactly the
    // subset of surviving server ids this session ordered.
    merged.push(localSurvivorSet.has(id) ? localSurvivors[nextLocal++] : id);
  }
  return merged;
}

export interface LayerDiffResult {
  diff: MapLayerDiffRequest;
  unsupported: boolean;
}

export type BuilderSaveStatus = 'saved' | 'unsaved' | 'saving' | 'failed';

/** Bridge between the layer-mutation hooks and useBuilderSave's diff baseline.
 *  fix(#392) added `add`; fix(#1778) added the symmetric `remove`. */
export interface SaveBaselineSync {
  add: (layer: MapLayerResponse) => void;
  remove: (layerIds: Iterable<string>) => void;
}

export function buildLayerDiff(
  baselineLayers: MapLayerResponse[],
  currentLayers: MapLayerResponse[],
  groupMeta: Record<string, FolderGroupMeta> = {},
): LayerDiffResult {
  // fix(#805): prepare BOTH sides through prepareLayersForPersistence so an
  // unchanged grouped map diffs empty. The baseline used to be prepared
  // without any groupMeta, so baseline children lacked the folderGroupExpanded
  // marker while current children carried it — every save of a grouped map
  // then emitted a spurious per-child style_config PATCH.
  // fix(#833): the baseline is prepared with its OWN persisted collapse state
  // (derived from the folderGroupExpanded markers it was loaded with), not the
  // live groupMeta — stamping the live value on both sides hid every collapse
  // change from the diff, so collapse-only edits persisted only when another
  // style_config edit happened to ride along in the same save.
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
    // fix(#767 B8): folder-group markers are written into style_config by
    // prepareLayersForPersistence for EVERY layer type, so a baseline that
    // carried them makes a null-out an intentional clear (ungrouping), not a
    // "field never populated" artifact. Without this, ungrouping a raster
    // layer never PATCHed (its empty style_config compacts to null and the
    // V-01 guard below swallowed it) and the group resurrected on reload.
    const baselineHadFolderGroup =
      getPersistedFolderGroup({ style_config: baseline.style_config } as MapLayerResponse) !== null;
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
      // fix(#767 B8): style_config is exempt when the baseline carried
      // folder-group markers — that null is a managed, deliberate erasure.
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
   *  the moment it is inserted (see the effect below for the full rationale).
   *  fix(#1778): `remove` is the delete half, called by the single and bulk
   *  delete paths alongside their savedLayerBaselineRef prune. */
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>;
  /** POLISH-01 (Phase 1233-01): set to true when the builder was opened with a
   *  ?add_dataset URL param so the first auto-capture is deferred until the
   *  layer-add effect has synced localLayers. Omit (or set false) for normal
   *  maps — existing behavior is preserved (empty map → idle path). */
  pendingLayerAdd?: boolean;
}

/** fix(#756): the state fields handleSave snapshots into its payloads. If any
 *  of them changes identity while the save's network round-trip is in flight,
 *  the dirty flag must survive the save — clearing it would absorb the
 *  mid-save edit into the baseline and let the query-invalidation resync
 *  overwrite it on screen. */
const SAVE_SNAPSHOT_FIELDS = [
  'localLayers',
  'groupMeta',
  'localName',
  'localDescription',
  'legendTitle',
  'dockNotes',
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
      // fix(#833 codex): stamp the live groupMeta expansion into the snapshot's
      // persisted markers. After a save clears the dirty flag, localLayers'
      // markers still carry the LOADED collapse state, so a verbatim copy made
      // the just-saved collapse invisible to the next diff (expand→save then
      // emitted nothing and reload restored the stale state).
      baselineLayersRef.current = stampPersistedFolderGroupExpanded(
        state.localLayers,
        state.groupMeta,
      );
    }
  }, [state.hasUnsavedChanges, state.localLayers, state.groupMeta]);

  // fix(#756): handleSave destructures `state` once at call time and then
  // awaits the network; this ref always points at the latest rendered state
  // so the post-await code can tell whether anything was edited meanwhile.
  // codex(#792 round 2): assigned during RENDER, not in a passive effect —
  // effects run after paint, so a mutation resolving right as an edit
  // commits could read the stale ref and clear the dirty flag anyway.
  const latestStateRef = useRef(state);
  latestStateRef.current = state;

  function editedDuringSave(
    sent: SaveState,
    sentPluginSet: ReadonlySet<string>,
  ): boolean {
    const latest = latestStateRef.current;
    // codex(#792): the plugins payload reads usePluginStore directly, not
    // SaveState, so a mid-save plugin toggle changes none of the fields
    // below — compare the store's Set identity too (every toggle produces
    // a new Set).
    if (usePluginStore.getState().activePlugins !== sentPluginSet) return true;
    return SAVE_SNAPSHOT_FIELDS.some((field) => sent[field] !== latest[field]);
  }

  useEffect(() => {
    // fix(#392): let layer-create paths register the server-created layer into the
    // Save-diff baseline. Marking the map dirty in the same update that inserts a
    // POST-created layer (the WR-02/CR-01 sort_order fix) otherwise leaves this
    // baseline unaware of the new server id, so buildLayerDiff reports it as
    // diff.added and the PATCH endpoint creates a duplicate. Register the PURE
    // server layer (no local grouping/reorder) so grouping/order still diff normally.
    state.saveBaselineSyncRef.current = {
      add: (layer: MapLayerResponse) => {
        if (!baselineLayersRef.current.some((l) => l.id === layer.id)) {
          baselineLayersRef.current = [...baselineLayersRef.current, { ...layer }];
        }
      },
      // fix(#1778): the mirror of `add`. The baseline effect above only
      // refreshes while the map is CLEAN, so a delete on an already-dirty map
      // left the deleted ids in this baseline; the next save then emitted them
      // in diff.removed and the backend rejected the whole diff. The delete
      // paths prune savedLayerBaselineRef already. This keeps the save-diff
      // baseline in step with them.
      remove: (layerIds: Iterable<string>) => {
        const ids = new Set(layerIds);
        if (ids.size === 0) return;
        baselineLayersRef.current = baselineLayersRef.current.filter((l) => !ids.has(l.id));
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
    // codex(#792): snapshot the plugin set the payload below will serialize,
    // so the post-await comparison can tell a mid-save plugin toggle apart.
    const sentPluginSet = usePluginStore.getState().activePlugins;

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
      // HT-13 note: the DEM editor's hillshade overlay (style_config.render_mode)
      // and 3D terrain binding (terrain_config) are now INDEPENDENT authorities.
      // A save that persists only one of them (e.g. the layer PATCH commits and
      // the metadata PUT fails) is therefore NOT a contradiction — it's an
      // incomplete save of two independent settings, coherent on reload and
      // recoverable by re-toggling. So the split PATCH+PUT path is safe and we
      // keep it, rather than forcing every combined save through the lossy
      // full-replacement PUT (which can null server-only layer fields — see the
      // #430 V-01 note below). The failed-save toast already prompts a retry.
      if (unsupported) {
        await updateMap.mutateAsync({ id, data: fullReplacementPayload });
      } else {
        if (hasDiff(diff)) {
          try {
            await patchMapLayers.mutateAsync({ id, diff });
          } catch (error) {
            // fix(#1778): a stale diff is a CONFLICT, not a missing endpoint.
            // Refetch the map, drop the ids the server no longer has, and retry
            // the PATCH. A failure here falls through to the outer catch with a
            // dedicated message; it must never reach the full PUT below.
            if (isStaleLayerDiffError(error)) {
              try {
                const fresh = await getMap(id);
                // GET /maps/{id} returns layers ordered by sort_order, so this is
                // the server's current sequence, which the order merge needs.
                const serverLayerIds = (fresh.layers ?? []).map((l) => l.id);
                const reconciled = reconcileLayerDiffWithServer(diff, serverLayerIds);
                if (hasDiff(reconciled)) {
                  await patchMapLayers.mutateAsync({ id, diff: reconciled });
                }
              } catch {
                throw new StaleLayerDiffError();
              }
              await updateMap.mutateAsync({ id, data: metadataPayload });
              baselineLayersRef.current = stampPersistedFolderGroupExpanded(localLayers, groupMeta);
              toast.warning(t('toasts.mapSavedAfterRemoteChange'));
              if (!editedDuringSave(state, sentPluginSet)) {
                state.setHasUnsavedChanges(false);
              }
              if (map && id) captureThumbnail(map, id, queryClient, localLayers);
              return;
            }
            if (!isUnsupportedLayerPatchError(error)) throw error;
            // fix(#430 V-01): this fallback converts a rejected partial PATCH into a
            // full PUT replacement (every layer re-serialized via toLayerInput,
            // including a lossy style_config/paint round-trip and — per V-14 —
            // fresh layer-row UUIDs). It used to report the same plain
            // "Map saved" success toast as a normal save, silently hiding that
            // a full re-sync occurred. Surface it instead so the user knows to
            // double-check layer styling rather than trusting a clean save.
            await updateMap.mutateAsync({ id, data: fullReplacementPayload });
            // fix(#833 codex): baseline carries the SENT collapse state, not
            // the loaded markers — see the baseline effect above.
            baselineLayersRef.current = stampPersistedFolderGroupExpanded(localLayers, groupMeta);
            toast.warning(t('toasts.mapSavedFullResync', {
              defaultValue: 'Map saved, but required a full re-sync. Please double-check layer styling.',
            }));
            // fix(#756): the baseline above is the SENT snapshot; only clear
            // the dirty flag when nothing was edited during the await, so a
            // mid-save edit stays diffable and guarded.
            if (!editedDuringSave(state, sentPluginSet)) {
              state.setHasUnsavedChanges(false);
            }
            if (map && id) captureThumbnail(map, id, queryClient, localLayers);
            return;
          }
        }
        await updateMap.mutateAsync({ id, data: metadataPayload });
      }

      // fix(#833 codex): baseline carries the SENT collapse state, not the
      // loaded markers — see the baseline effect above.
      baselineLayersRef.current = stampPersistedFolderGroupExpanded(localLayers, groupMeta);
      toast.success(t('toasts.mapSaved'));
      // fix(#756): the baseline above is the SENT snapshot; only clear the
      // dirty flag when nothing was edited during the network await —
      // otherwise the baseline effect would absorb the mid-save edit and the
      // query-invalidation resync would overwrite it on screen.
      if (!editedDuringSave(state, sentPluginSet)) {
        state.setHasUnsavedChanges(false);
      }

      // Capture thumbnail and upload (fire-and-forget)
      // Use `map` captured before mutate — mapInstanceRef.current may be
      // transiently null during re-render (callback ref identity change).
      if (map && id) {
        captureThumbnail(map, id, queryClient, localLayers);
      }
    } catch (err) {
      setLastSaveFailed(true);
      // fix(#1778): the map's layers changed in another session and the diff
      // could not be reconciled. Say so, rather than reporting a generic
      // failure or overwriting the map with this session's stale snapshot.
      if (err instanceof StaleLayerDiffError) {
        toast.error(t('toasts.saveConflictReload'));
        return;
      }
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

          // fix(#769): synthetic group:folder rows inherit visible/show_in_legend
          // from their first child — exclude them or the exported PNG ships a
          // phantom legend row per folder group (mirrors LegendPlugin's filter).
          const legendLayers = state.localLayers.filter(
            (l) => l.visible && l.show_in_legend !== false && !isFolderGroupLayer(l),
          );
          const legendHeaderH = legendLayers.length > 0 ? 32 * dpr : 0;
          const legendRowH = 22 * dpr;
          const legendBlockH =
            legendLayers.length > 0
              ? 12 * dpr + legendHeaderH + legendLayers.length * legendRowH + 12 * dpr
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

          // feat(#1486): the attribution band has to be MEASURED before the
          // canvas is sized, since its height feeds totalH. It measures on this
          // same context rather than a scratch canvas — `off` has its width but
          // not yet its height, and setting the height below resets the context
          // state (not the measurement, which is already a number).
          //
          // NOT gated on showBranding: "Powered by GeoLens" is promotion an
          // enterprise licence may suppress, a basemap or dataset credit is a
          // licensing obligation and is drawn either way.
          //
          // fix(#1541 codex P2 round 2): the band is the only elastic term in
          // totalH, so it gets the height a browser will still encode, less
          // what the fixed blocks have already spent. Unbounded, a
          // contract-maximum map (200 layers x 5,000 characters of credit)
          // asked for a canvas past the engine's limits, `toBlob` returned
          // null and the PNG export failed outright.
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

          // fix(#1479 Codex P2 round 1): the map band, and only the map band,
          // gets the space color under the canvas — the globe's void is
          // transparent, so it would otherwise composite onto the white fill
          // above and export as a sphere on white. The title/legend/footer
          // bands stay white because their text is #0a0a0a on white by design.
          if (hasGlobeSpaceBackdrop(map)) {
            ctx.fillStyle = MAP_COLORS.exportImage.globeBackground;
            ctx.fillRect(0, cursorY, totalW, mapHeight);
          }
          ctx.drawImage(srcCanvas, 0, cursorY);
          cursorY += mapHeight;

          if (legendLayers.length > 0) {
            cursorY += 12 * dpr;
            ctx.fillStyle = MAP_COLORS.exportImage.text;
            ctx.font = `600 ${14 * dpr}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
            // D5: honor the custom map-level legend title (ENH-06) like the
            // on-screen legend; fall back to the localized default header.
            const legendHeaderText = state.legendTitle?.trim()
              ? state.legendTitle.trim()
              : t('export.legendHeader', { defaultValue: 'Legend' });
            ctx.fillText(legendHeaderText, pad, cursorY);
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
              const solidFill = colors.find((c) => !!c) || MAP_COLORS.icon.fallback;
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
              ctx.strokeStyle = (!strokeHidden && hints.strokeColor) || MAP_COLORS.previewOutline;
              ctx.lineWidth = Math.max(1, dpr);
              ctx.strokeRect(pad, rowY, swatchSize, swatchSize);
              ctx.fillStyle = MAP_COLORS.exportImage.text;
              // D5: was `display_name || dataset_name`, which dropped the
              // per-entry legendLabel override the on-screen legend renders.
              ctx.fillText(
                legendEntryName(layer),
                pad + swatchSize + 10 * dpr,
                cursorY + (legendRowH - 13 * dpr) / 2,
              );
              cursorY += legendRowH;
            }
          }

          // feat(#1486): between the legend and the branding footer, on white
          // rather than over imagery — so no scrim, and no credit is ever
          // dropped for want of room (it wraps to a second line instead).
          //
          // Positioned off the block heights rather than off `cursorY`: the
          // legend loop leaves the cursor 12*dpr above its own block bottom
          // (it never adds legendBlockH's trailing pad), so following the
          // cursor would draw the band into the legend's bottom padding and
          // leave the same 12*dpr of dead white at the foot of the canvas.
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
    captureThumbnail(map, state.mapId, queryClient, localLayersRef.current, captureSignalRef.current, layersRef, 'auto');
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
        // data-state="open" on its content element; we check the role-dialog
        // selector (covers Dialog and, via role="dialog", Sheet — which also
        // carries data-slot="sheet-content").
        // ux(#777): Radix AlertDialog content renders role="alertdialog", NOT
        // role="dialog" — matched explicitly so the unsaved-changes leave
        // dialog (now an AlertDialog) still suppresses Cmd+S. The builder's
        // inline row confirms also use role="alertdialog" but have no
        // data-state attribute, so they intentionally do not match.
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
