import { useCallback, useEffect, useRef } from 'react';
import { getEnvConfig } from '@/lib/env';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import type { Map as MaplibreMap } from 'maplibre-gl';
import maplibregl from 'maplibre-gl';
import { getMvtSourceLayerName } from '@/lib/tile-utils';

/** Empty GeoJSON FeatureCollection */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

// fix(#394) VT-04: use the shared helper — a local duplicate is exactly the
// silent-drift class the source-layer parity test pins down.
const getSourceLayerName = getMvtSourceLayerName;

interface UseMapLayersOptions {
  tableName: string | null;
  geometryType: string | null;
  rasterTileUrl?: string | null;
  tileVersion?: string | null;
  // Matches ``buildSignedTileUrl``'s parameter type — the hook previously
  // typed this as ``string | null`` which was incompatible with the
  // signed-token object shape it's actually passing through.
  tileToken: { sig: string; exp: number; scope: string } | null;
  tileConfigCdnBaseUrl?: string;
  mvtSourceLayerPrefix?: string | null;
  /** Whether the tenant-aware source-layer prefix has finished resolving. */
  mvtSourceLayerReady?: boolean;
  mapRef: React.RefObject<MaplibreMap | null>;
  /** Column name containing height/elevation data for 3D extrusion (polygon datasets only) */
  elevationColumn?: string | null;
}

export function useMapLayers({
  tableName,
  geometryType,
  rasterTileUrl,
  tileVersion,
  tileToken,
  tileConfigCdnBaseUrl,
  mvtSourceLayerPrefix,
  mvtSourceLayerReady = true,
  mapRef,
  elevationColumn,
}: UseMapLayersOptions) {
  const vectorLayersAdded = useRef(false);
  const rasterLayersAdded = useRef(false);

  const addVectorLayers = useCallback(
    (map: MaplibreMap) => {
      if (!mvtSourceLayerReady) return;
      if (!tableName || vectorLayersAdded.current) return;
      if (!geometryType) return;
      if (map.getSource('vector-tile-source')) return;

      try {
        const sourceLayer = getSourceLayerName(tableName, mvtSourceLayerPrefix);
        const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfigCdnBaseUrl;

        map.addSource('vector-tile-source', {
          type: 'vector',
          tiles: [buildSignedTileUrl(tableName, tileToken, tileBaseUrl, tileVersion)],
          minzoom: 1,
          maxzoom: 22,
        });

        const upperType = geometryType.toUpperCase();
        const isPoint = upperType.includes('POINT');
        const isLine = upperType.includes('LINE');
        // fix(#430 codex r21): a generic sketch dataset (GEOMETRY sentinel /
        // GEOMETRYCOLLECTION) can hold every family at once — install all
        // three renderers with $type filters so no family disappears when the
        // display type degrades to generic after a cross-family draw.
        const isGeneric =
          upperType === 'GEOMETRY' || upperType === 'GEOMETRYCOLLECTION';

        if (isGeneric) {
          map.addLayer({
            id: 'vector-fill',
            type: 'fill',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
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
            filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
            paint: {
              'line-color': MAP_COLORS.default.stroke,
              'line-width': 1,
            },
          });
          map.addLayer({
            id: 'vector-lines',
            type: 'line',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]],
            paint: {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
          });
          map.addLayer({
            id: 'vector-points',
            type: 'circle',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]],
            paint: {
              'circle-radius': 4,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
          });
        } else if (isPoint) {
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
        } else if (elevationColumn) {
          // 3D extruded polygons driven by the elevation/height column
          map.addLayer({
            id: 'vector-extrusion',
            type: 'fill-extrusion',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'fill-extrusion-color': MAP_COLORS.default.fill,
              // Null-safe height expression (#14): only read the property when
              // present, then coalesce the raw value to 0 BEFORE ``to-number`` so
              // a feature with a null/missing height never reaches a numeric
              // operator as ``null`` (which throws the maplibre worker error
              // "Expected value to be of type number, but found null").
              'fill-extrusion-height': [
                'max',
                [
                  'case',
                  ['has', elevationColumn],
                  ['to-number', ['coalesce', ['get', elevationColumn], 0], 0],
                  0,
                ],
                0,
              ],
              'fill-extrusion-base': 0,
              'fill-extrusion-opacity': 0.8,
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
        if (import.meta.env.DEV) console.warn('addVectorLayers: failed to add sources/layers', e);
      }
    },
    [tableName, geometryType, tileConfigCdnBaseUrl, mvtSourceLayerPrefix, mvtSourceLayerReady, tileToken, tileVersion, elevationColumn],
  );

  // DatasetMap's load event can precede the settings request. Re-run the
  // vector setup when that request settles instead of leaving the map empty
  // (or creating it early with the wrong immutable source-layer name).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mvtSourceLayerReady) return;
    addVectorLayers(map);
  }, [addVectorLayers, mapRef, mvtSourceLayerReady]);

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
        if (import.meta.env.DEV) console.warn('addRasterLayers: failed', e);
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
      if (import.meta.env.DEV) console.warn('addOverlaySource: failed to add sources/layers', e);
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
