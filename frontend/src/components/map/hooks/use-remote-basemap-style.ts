import { useEffect, useRef, useState, type RefObject } from 'react';
import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl';
import { sanitizeMaplibreStyle } from '@/lib/basemap-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import { clearTerrainForStyleSwap } from '@/components/builder/map-sync';

interface RemoteBasemapStyleOptions {
  /** Output of `toMaplibreStyle` — a style URL or an inline StyleSpecification. */
  styleValue: string | StyleSpecification;
  mapRef: RefObject<MaplibreMap | null>;
  /** Console prefix for the DEV-only sanitize-failure warning. */
  logLabel: string;
  /** ViewerMap behavior: on fetch failure, hand MapLibre the raw style URL so
   *  it performs its own (second) fetch. BuilderMap deliberately does NOT do
   *  this (Phase 1051 WR-06: the second fetch is uncancelable and can flash an
   *  intermediate state) — it keeps the placeholder and surfaces a notice via
   *  `onFetchError` instead. */
  fallbackToRawUrlOnError?: boolean;
  /** Called when a remote style fetch is about to start (after the placeholder
   *  style is installed). BuilderMap resets its first-load latch here. */
  onFetchStart?: () => void;
  /** Called after the sanitized style has been applied. */
  onFetchSuccess?: () => void;
  /** Called when the fetch/sanitize failed (not on unmount/abort). */
  onFetchError?: () => void;
}

/**
 * chore(#835): the single remote-basemap-style fetch effect shared by
 * BuilderMap and ViewerMap (DatasetMap never fetches style JSON in app code —
 * its imperative `setStyle` + `transformStyle` path lets MapLibre fetch).
 *
 * Remote GL styles can reference sprite patterns that are unavailable in
 * their published sprite sheet. Fetch and sanitize first so MapLibre never
 * emits noisy missing-image warnings. While the fetch is in flight a plain
 * background placeholder is shown; inline styles (blank basemap, raster XYZ
 * wrappers) and non-`/styles/` URLs pass through untouched.
 *
 * Any future fix to this fetch path (e.g. a retry) lands in all consumers at
 * once instead of drifting per map.
 */
export function useRemoteBasemapStyle({
  styleValue,
  mapRef,
  logLabel,
  fallbackToRawUrlOnError = false,
  onFetchStart,
  onFetchSuccess,
  onFetchError,
}: RemoteBasemapStyleOptions): string | StyleSpecification {
  const [mapStyle, setMapStyle] = useState(styleValue);

  // Callbacks are read through a ref at call time so their identity never
  // re-triggers the fetch effect (deps stay [styleValue], matching the
  // pre-extraction effects in BuilderMap/ViewerMap).
  const callbacksRef = useRef({ onFetchStart, onFetchSuccess, onFetchError });
  callbacksRef.current = { onFetchStart, onFetchSuccess, onFetchError };

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const map = mapRef.current;

    if (map) {
      clearTerrainForStyleSwap(map);
    }

    if (typeof styleValue !== 'string' || !styleValue.includes('/styles/')) {
      setMapStyle(styleValue);
      return () => {
        controller.abort();
      };
    }

    setMapStyle({
      version: 8,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': MAP_COLORS.canvas.background },
        },
      ],
    });

    callbacksRef.current.onFetchStart?.();

    fetch(styleValue, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Basemap style request failed: ${response.status}`);
        return response.json() as Promise<StyleSpecification>;
      })
      .then((style) => {
        if (!cancelled) {
          setMapStyle(sanitizeMaplibreStyle(style));
          callbacksRef.current.onFetchSuccess?.();
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.warn(`[${logLabel}] Basemap style sanitization failed:`, error);
        if (!cancelled) {
          if (fallbackToRawUrlOnError) setMapStyle(styleValue);
          callbacksRef.current.onFetchError?.();
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // logLabel/fallbackToRawUrlOnError are mount-constant per consumer.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- styleValue is the sole reactive input (pre-extraction parity)
  }, [styleValue]);

  return mapStyle;
}
