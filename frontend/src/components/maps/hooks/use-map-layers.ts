import { useCallback, useEffect, useMemo, useRef } from 'react';
import { getEnvConfig } from '@/lib/env';
import { MAP_COLORS } from '@/lib/map-colors';
import { toMapLibreAttribution } from '@/lib/attribution-safety';
import type { Map as MaplibreMap, VectorSourceSpecification, VectorTileSource } from 'maplibre-gl';
import { getMvtSourceLayerName } from '@/lib/tile-utils';
import type { VectorTileToken } from '@/api/tiles';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';
import { mixedLinesLayerId, mixedPointsLayerId } from '@/components/builder/layer-adapters/mixed-adapter';
import { describeLayers, getSourceIdForLayer } from '@/components/builder/layer-description';
import type { SyncLayerInput } from '@/components/builder/map-sync';

/** Empty GeoJSON FeatureCollection */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

// fix(#394) VT-04: use the shared helper — a local duplicate is exactly the
// silent-drift class the source-layer parity test pins down.
const getSourceLayerName = getMvtSourceLayerName;

/** The prefix of the ids the preview gives its dataset's source and layers. */
export const PREVIEW_ID_PREFIX = 'preview-';
/** The preview draws its dataset as one default layer with this id. */
const PREVIEW_LAYER_KEY = 'dataset';
const PREVIEW_IDS = getCompanionLayerIds(PREVIEW_LAYER_KEY, PREVIEW_ID_PREFIX);

/** The preview layers that draw the dataset's features. */
export const PREVIEW_FEATURE_LAYER_IDS = [
  PREVIEW_IDS.layer,
  PREVIEW_IDS.mixedLines,
  PREVIEW_IDS.mixedPoints,
  PREVIEW_IDS.extrusion,
];
/** Every layer the preview draws its dataset with. */
export const PREVIEW_LAYER_IDS = [...PREVIEW_FEATURE_LAYER_IDS, PREVIEW_IDS.outline];

/** The source the preview draws a dataset table from. */
export function previewSourceId(tableName: string) {
  return getSourceIdForLayer({ id: PREVIEW_LAYER_KEY, dataset_table_name: tableName }, PREVIEW_ID_PREFIX);
}

/** What the preview knows about its dataset. */
export interface PreviewDataset {
  datasetId?: string;
  tableName: string;
  geometryType: string;
  tileVersion?: string | null;
  attribution?: string | null;
  elevationColumn?: string | null;
}

/** The one layer the preview draws: the whole dataset in the default style. */
export function toPreviewSyncInput(dataset: PreviewDataset): SyncLayerInput {
  return {
    id: PREVIEW_LAYER_KEY,
    dataset_id: dataset.datasetId ?? '',
    dataset_table_name: dataset.tableName,
    dataset_geometry_type: dataset.geometryType,
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    style_config: dataset.elevationColumn
      ? { builder: { heightColumn: dataset.elevationColumn, extrusionMinZoom: 0 } }
      : null,
    attribution: toMapLibreAttribution(dataset.attribution),
    tile_version: dataset.tileVersion,
    // No bounds: a source keeps the bounds it was added with, and a feature
    // drawn outside the stored extent still has to draw.
  };
}

/** The preview's layer and the source it draws from, as the layer description gives them. */
export function describePreview(
  dataset: PreviewDataset,
  tiles: {
    token: VectorTileToken | null;
    tileBaseUrl: string | undefined;
    sourceLayerPrefix: string | null | undefined;
  },
) {
  const layer = toPreviewSyncInput(dataset);
  const { sources, layers: [described] } = describeLayers([layer], {
    idPrefix: PREVIEW_ID_PREFIX,
    origin: window.location.origin,
    tileBaseUrl: tiles.tileBaseUrl,
    sourceLayerPrefix: tiles.sourceLayerPrefix,
    tokens: new Map(tiles.token ? [[layer.dataset_id, tiles.token]] : []),
    boundedGeoJson: new Map(),
  });
  return { layer: described, source: sources.get(described.sourceId) as VectorSourceSpecification };
}

interface UseMapLayersOptions {
  datasetId?: string;
  tableName: string | null;
  geometryType: string | null;
  rasterTileUrl?: string | null;
  tileVersion?: string | null;
  /** Signs the vector tile URLs; without one they go unsigned. */
  tileToken: VectorTileToken | null;
  tileConfigCdnBaseUrl?: string;
  mvtSourceLayerPrefix?: string | null;
  /** Whether the tenant-aware source-layer prefix has finished resolving. */
  mvtSourceLayerReady?: boolean;
  mapRef: React.RefObject<MaplibreMap | null>;
  /** Column name containing height/elevation data for 3D extrusion (polygon datasets only) */
  elevationColumn?: string | null;
  /** fix(#1472 review): the dataset's required credit line. Applied as the
   *  MapLibre source `attribution`, which the map's default attribution control
   *  reads off whichever sources are live — the preview map has no explicit
   *  control to pass `customAttribution` to. */
  attribution?: string | null;
}

export function useMapLayers({
  datasetId,
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
  attribution,
}: UseMapLayersOptions) {
  const vectorLayersAdded = useRef(false);
  const rasterLayersAdded = useRef(false);
  // MapLibre renders attribution as innerHTML. See lib/attribution-safety.
  const safeAttribution = toMapLibreAttribution(attribution);

  // Describing needs the resolved tenant prefix for its MVT layer names.
  const preview = useMemo(() => {
    if (!mvtSourceLayerReady || mvtSourceLayerPrefix === null || !tableName || !geometryType) return null;
    return describePreview(
      { datasetId, tableName, geometryType, tileVersion, attribution, elevationColumn },
      {
        token: tileToken,
        tileBaseUrl: getEnvConfig().TILE_BASE_URL || tileConfigCdnBaseUrl,
        sourceLayerPrefix: mvtSourceLayerPrefix,
      },
    );
  }, [datasetId, tableName, geometryType, tileVersion, attribution, elevationColumn, tileToken, tileConfigCdnBaseUrl, mvtSourceLayerPrefix, mvtSourceLayerReady]);

  const addVectorLayers = useCallback(
    (map: MaplibreMap) => {
      if (!preview || vectorLayersAdded.current) return;
      const { id, sourceId, sourceLayer, drawsAs } = preview.layer;
      if (map.getSource(sourceId)) return;

      try {
        map.addSource(sourceId, preview.source);

        // fix(#430 codex r21): a generic sketch dataset (GEOMETRY sentinel /
        // GEOMETRYCOLLECTION) can hold every family at once — install all
        // three renderers with $type filters so no family disappears when the
        // display type degrades to generic after a cross-family draw.
        if (drawsAs === 'mixed') {
          map.addLayer({
            id,
            type: 'fill',
            source: sourceId,
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
            paint: {
              'fill-color': MAP_COLORS.default.fill,
              'fill-opacity': MAP_COLORS.default.fillOpacity,
            },
          });
          map.addLayer({
            id: `${id}-outline`,
            type: 'line',
            source: sourceId,
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
            paint: {
              'line-color': MAP_COLORS.default.stroke,
              'line-width': 1,
            },
          });
          map.addLayer({
            id: mixedLinesLayerId(id),
            type: 'line',
            source: sourceId,
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]],
            paint: {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
          });
          map.addLayer({
            id: mixedPointsLayerId(id),
            type: 'circle',
            source: sourceId,
            'source-layer': sourceLayer,
            filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]],
            paint: {
              'circle-radius': 4,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
          });
        } else if (drawsAs === 'circle') {
          map.addLayer({
            id,
            type: 'circle',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: {
              'circle-radius': 4,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
          });
        } else if (drawsAs === 'line') {
          map.addLayer({
            id,
            type: 'line',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
          });
        } else if (elevationColumn) {
          // 3D extruded polygons driven by the elevation/height column
          map.addLayer({
            id: `${id}-extrusion`,
            type: 'fill-extrusion',
            source: sourceId,
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
            id,
            type: 'fill',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: {
              'fill-color': MAP_COLORS.default.fill,
              'fill-opacity': MAP_COLORS.default.fillOpacity,
            },
          });
          map.addLayer({
            id: `${id}-outline`,
            type: 'line',
            source: sourceId,
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
    [preview, elevationColumn],
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
        // #1362 codex r2: the raster tile route is a fixed per-dataset path
        // (never re-added, see the guard above), and the api response for a
        // public dataset carries `Cache-Control: public, max-age=3600` — so
        // the browser's OWN cache can keep serving pre-replace tile bytes
        // for an identical URL for up to an hour even after this source is
        // freshly re-added on remount. Bust that with tileVersion (the
        // dataset's updated_at) the same way the vector source already does
        // via buildSignedTileUrl.
        // fix(#1372, #2007): the server embeds `?v=<tile_cache_version>` and
        // `pv=<publication_version>` (nginx's shared cache keys on both) — any
        // server query supersedes this client-side append, which would both
        // make nginx key on the wrong `v` and emit a second `?`.
        const hasServerVersion = rasterTileUrl.includes('?');
        const versionedTileUrl =
          tileVersion && !hasServerVersion
            ? `${window.location.origin}${rasterTileUrl}?v=${encodeURIComponent(tileVersion)}`
            : `${window.location.origin}${rasterTileUrl}`;
        map.addSource('raster-tile-source', {
          type: 'raster',
          tiles: [versionedTileUrl],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 22,
          ...(safeAttribution ? { attribution: safeAttribution } : {}),
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
    [rasterTileUrl, tileVersion, safeAttribution],
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
  const vectorSourceId = preview?.layer.sourceId;
  const vectorTileUrl = preview?.source.tiles?.[0];
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tileToken || !vectorSourceId || !vectorTileUrl) return;
    const source = map.getSource(vectorSourceId);
    if (source && 'setTiles' in source) {
      (source as VectorTileSource).setTiles([vectorTileUrl]);
    }
  }, [tileToken, vectorSourceId, vectorTileUrl, mapRef]);

  return { addVectorLayers, addRasterLayers, addOverlaySource };
}

export { getSourceLayerName };
