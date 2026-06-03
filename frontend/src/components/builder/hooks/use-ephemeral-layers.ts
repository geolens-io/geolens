import { useState, useEffect, useCallback } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';

const EPHEMERAL_LAYERS = [
  'ephemeral-result-fill',
  'ephemeral-result-outline',
  'ephemeral-result-line',
  'ephemeral-result-circle',
] as const;
const EPHEMERAL_SOURCE = 'ephemeral-result';

export function useEphemeralLayers(
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
) {
  const [ephemeralResult, setEphemeralResult] = useState<{
    geojson: GeoJSON.FeatureCollection;
    bbox: [number, number, number, number];
  } | null>(null);

  const clearEphemeralLayer = useCallback(() => {
    const map = mapInstanceRef.current;
    if (map) {
      for (const layerId of EPHEMERAL_LAYERS) {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
      }
      if (map.getSource(EPHEMERAL_SOURCE)) map.removeSource(EPHEMERAL_SOURCE);
    }
    setEphemeralResult(null);
  }, [mapInstanceRef]);

  // Add ephemeral GeoJSON layers to the map when result changes
  useEffect(() => {
    if (!ephemeralResult) return;
    const map = mapInstanceRef.current;
    if (!map) return;

    function addLayers() {
      if (!map || !ephemeralResult) return;
      // Remove any existing ephemeral layers/source first
      for (const layerId of EPHEMERAL_LAYERS) {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
      }
      if (map.getSource(EPHEMERAL_SOURCE)) map.removeSource(EPHEMERAL_SOURCE);

      map.addSource(EPHEMERAL_SOURCE, {
        type: 'geojson',
        data: ephemeralResult.geojson,
      });

      // Polygon fill
      map.addLayer({
        id: 'ephemeral-result-fill',
        type: 'fill',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Polygon'],
        paint: { 'fill-color': '#f97316', 'fill-opacity': 0.15 },
      });

      // Polygon outline
      map.addLayer({
        id: 'ephemeral-result-outline',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Polygon'],
        paint: { 'line-color': '#f97316', 'line-width': 2, 'line-dasharray': [3, 2] },
      });

      // Line layer
      map.addLayer({
        id: 'ephemeral-result-line',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'LineString'],
        paint: { 'line-color': '#f97316', 'line-width': 2.5, 'line-dasharray': [3, 2] },
      });

      // Point layer
      map.addLayer({
        id: 'ephemeral-result-circle',
        type: 'circle',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': '#f97316',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      });

      // Auto-zoom to bounds
      const [west, south, east, north] = ephemeralResult.bbox;
      map.fitBounds([[west, south], [east, north]], { padding: 40, maxZoom: 18 });
    }

    if (map.isStyleLoaded()) {
      addLayers();
    } else {
      map.once('style.load', addLayers);
    }

    return () => {
      map.off('style.load', addLayers);
    };
  }, [ephemeralResult, mapInstanceRef]);

  const handleQueryResult = useCallback((geojson: GeoJSON.FeatureCollection, bbox: [number, number, number, number]) => {
    setEphemeralResult({ geojson, bbox });
  }, []);

  return {
    ephemeralResult,
    handleQueryResult,
    handleDismissEphemeral: clearEphemeralLayer,
  };
}
