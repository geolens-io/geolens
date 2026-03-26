import { useCallback, useEffect, useRef } from 'react';
import { getEnvConfig } from '@/lib/env';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import type { Map as MaplibreMap } from 'maplibre-gl';
import maplibregl from 'maplibre-gl';

/** Empty GeoJSON FeatureCollection */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function getSourceLayerName(tableName: string): string {
  return `data.${tableName}`;
}

interface UseMapLayersOptions {
  tableName: string | null;
  geometryType: string | null;
  rasterTileUrl?: string | null;
  tileVersion?: string | null;
  tileToken: string | null;
  tileConfigCdnBaseUrl?: string;
  mapRef: React.RefObject<MaplibreMap | null>;
}

export function useMapLayers({
  tableName,
  geometryType,
  rasterTileUrl,
  tileVersion,
  tileToken,
  tileConfigCdnBaseUrl,
  mapRef,
}: UseMapLayersOptions) {
  const vectorLayersAdded = useRef(false);
  const rasterLayersAdded = useRef(false);

  const addVectorLayers = useCallback(
    (map: MaplibreMap) => {
      if (!tableName || vectorLayersAdded.current) return;
      if (!geometryType) return;
      if (map.getSource('vector-tile-source')) return;

      try {
        const sourceLayer = getSourceLayerName(tableName);
        const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfigCdnBaseUrl;

        map.addSource('vector-tile-source', {
          type: 'vector',
          tiles: [buildSignedTileUrl(tableName, tileToken, tileBaseUrl, tileVersion)],
          minzoom: 1,
          maxzoom: 22,
        });

        const isPoint = geometryType.toUpperCase().includes('POINT');
        const isLine = geometryType.toUpperCase().includes('LINE');

        if (isPoint) {
          map.addLayer({
            id: 'vector-points',
            type: 'circle',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'circle-radius': 4,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
          });
        } else if (isLine) {
          map.addLayer({
            id: 'vector-lines',
            type: 'line',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
          });
        } else {
          map.addLayer({
            id: 'vector-fill',
            type: 'fill',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'fill-color': MAP_COLORS.default.fill,
              'fill-opacity': MAP_COLORS.default.fillOpacity,
            },
          });
          map.addLayer({
            id: 'vector-outline',
            type: 'line',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'line-color': MAP_COLORS.default.stroke,
              'line-width': 1,
            },
          });
        }

        vectorLayersAdded.current = true;
      } catch (e) {
        console.warn('addVectorLayers: failed to add sources/layers', e);
      }
    },
    [tableName, geometryType, tileConfigCdnBaseUrl, tileToken, tileVersion],
  );

  const addRasterLayers = useCallback(
    (map: MaplibreMap) => {
      if (!rasterTileUrl || rasterLayersAdded.current) return;
      if (map.getSource('raster-tile-source')) return;
      try {
        map.addSource('raster-tile-source', {
          type: 'raster',
          tiles: [`${window.location.origin}${rasterTileUrl}`],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 22,
        });
        map.addLayer({
          id: 'raster-layer',
          type: 'raster',
          source: 'raster-tile-source',
          paint: { 'raster-opacity': 1 },
        });
        rasterLayersAdded.current = true;
      } catch (e) {
        console.warn('addRasterLayers: failed', e);
      }
    },
    [rasterTileUrl],
  );

  const addOverlaySource = useCallback((map: MaplibreMap) => {
    if (map.getSource('drawn-overlay')) return;

    try {
      map.addSource('drawn-overlay', {
        type: 'geojson',
        data: EMPTY_FC,
      });

      map.addLayer({
        id: 'drawn-overlay-points',
        type: 'circle',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': MAP_COLORS.drawing.fill,
          'circle-stroke-color': MAP_COLORS.drawing.stroke,
          'circle-stroke-width': 2,
        },
      });

      map.addLayer({
        id: 'drawn-overlay-lines',
        type: 'line',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'LineString'],
        paint: {
          'line-color': MAP_COLORS.drawing.fill,
          'line-width': 3,
        },
      });

      map.addLayer({
        id: 'drawn-overlay-fill',
        type: 'fill',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'fill-color': MAP_COLORS.drawing.fill,
          'fill-opacity': MAP_COLORS.drawing.fillOpacity,
        },
      });

      map.addLayer({
        id: 'drawn-overlay-outline',
        type: 'line',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'line-color': MAP_COLORS.drawing.stroke,
          'line-width': 2,
        },
      });
    } catch (e) {
      console.warn('addOverlaySource: failed to add sources/layers', e);
    }
  }, []);

  // Clean up vector layers on unmount or prop change
  useEffect(() => {
    return () => { vectorLayersAdded.current = false; };
  }, [tableName]);

  // Clean up raster layers on unmount or tile URL change
  useEffect(() => {
    return () => { rasterLayersAdded.current = false; };
  }, [rasterTileUrl]);

  // Update tile URLs in-place when token refreshes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tileToken || !tableName) return;
    const source = map.getSource('vector-tile-source');
    if (source && 'setTiles' in source) {
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfigCdnBaseUrl;
      const newUrl = buildSignedTileUrl(tableName, tileToken, tileBaseUrl, tileVersion);
      (source as maplibregl.VectorTileSource).setTiles([newUrl]);
    }
  }, [tileToken, tableName, tileConfigCdnBaseUrl, tileVersion, mapRef]);

  return { addVectorLayers, addRasterLayers, addOverlaySource };
}

export { getSourceLayerName };
