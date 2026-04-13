import { useEffect, useRef, useMemo } from 'react';
import { fetchGeoJsonZ } from '@/api/geojson-z';
import type { SharedLayerResponse } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

/**
 * Fetches GeoJSON with Z coordinates for small 3D datasets (feature_count <= 5000).
 * These datasets are rendered via GeoJSON sources instead of MVT to preserve
 * elevation data.
 */
export function useGeoJsonZ(
  layers: SharedLayerResponse[],
  mapRef: React.RefObject<MaplibreMap | null>,
  mapReady: boolean,
  options?: { apiKey?: string; embedToken?: string },
) {
  const apiKey = options?.apiKey;
  const embedToken = options?.embedToken;

  const geojsonDataRef = useRef<Map<string, GeoJSON.FeatureCollection>>(new Map());

  const geojsonZLayers = useMemo(
    () => layers.filter((l) => l.is_3d && l.feature_count != null && l.feature_count <= 5000),
    [layers],
  );

  useEffect(() => {
    if (geojsonZLayers.length === 0) return;
    let cancelled = false;
    async function fetchAll() {
      const newMap = new Map<string, GeoJSON.FeatureCollection>();
      await Promise.all(
        geojsonZLayers.map(async (layer) => {
          try {
            const data = await fetchGeoJsonZ(layer.dataset_id, { apiKey, embedToken });
            if (!cancelled) {
              newMap.set(String(layer.sort_order), data as GeoJSON.FeatureCollection);
            }
          } catch (e) {
            if (import.meta.env.DEV) console.warn(`[ViewerMap] GeoJSON-Z fetch failed for ${layer.dataset_id}:`, e);
          }
        }),
      );
      if (!cancelled) {
        if (newMap.size === 0 && geojsonZLayers.length > 0) {
          if (import.meta.env.DEV) console.warn('[ViewerMap] All GeoJSON-Z fetches failed — layers will render as 2D MVT');
        }
        geojsonDataRef.current = newMap;
        const map = mapRef.current;
        if (map && mapReady) {
          map.triggerRepaint();
        }
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [geojsonZLayers, apiKey, embedToken, mapReady, mapRef]);

  return { geojsonDataRef };
}
