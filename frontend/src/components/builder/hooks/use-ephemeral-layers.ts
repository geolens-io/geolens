import { useState, useEffect, useCallback } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toFitBounds } from '@/lib/bbox';
import { MAP_COLORS } from '@/lib/map-colors';

const EPHEMERAL_LAYERS = [
  'ephemeral-result-fill',
  'ephemeral-result-outline',
  'ephemeral-result-line',
  'ephemeral-result-circle',
] as const;
const EPHEMERAL_SOURCE = 'ephemeral-result';

/** The params needed to reconstruct a chat run_analysis preview in the Analysis
 *  panel, so "Save as dataset" can prefill it. */
export interface EphemeralAnalysisHandoff {
  operation: 'buffer' | 'centroid';
  layerId: string;
  distanceMeters?: number;
}

export function useEphemeralLayers(
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
) {
  const [ephemeralResult, setEphemeralResult] = useState<{
    geojson: GeoJSON.FeatureCollection;
    bbox: [number, number, number, number];
    /** Set when the server capped the result, so the preview surface can
     *  disclose "N of TOTAL" instead of passing a capped preview off as the
     *  whole answer. This hook feeds both the builder's stack row and the badge
     *  (viewer, and the builder's <1100px rail), so the field is
     *  surface-agnostic. */
    truncated?: boolean;
    totalCount?: number;
    /** Set when totalCount was computed against the map's viewport rather than
     *  the whole dataset, so "N of TOTAL" can name the previewed extent. Chat
     *  previews never set it: they send no bbox, so their totalCount (when
     *  present) is the whole-dataset count. */
    viewportScoped?: boolean;
    /** Present when the overlay came from a chat run_analysis preview the
     *  builder can hand off to the Analysis panel. */
    analysis?: EphemeralAnalysisHandoff;
    /** The chat prompt that produced this preview, used to suggest a title when
     *  the preview is saved as a dataset (as AnalysisPanel's prefill does).
     *  Absent for Analysis-panel previews (they carry `analysis`) and for the
     *  cold-load handoff, which stashes geometry only. */
    prompt?: string;
    /** Stamped by the Analysis panel's own previews so its stale-restore cleanup
     *  can tell them from a chat result sharing this slot; it must never clear
     *  an overlay someone else drew. */
    source?: 'analysis-panel';
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

      // Deliberately no `attribution`, unlike other dataset-backed sources in the
      // builder: this renders the output of a spatial operation, not a dataset.
      // The geometry is computed, transient (cleared on the next run, never
      // persisted or exported), and the hook receives only the result GeoJSON
      // with no handle on the input datasets. Crediting derived output belongs
      // with the analysis feature that knows its inputs.
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
        paint: { 'fill-color': MAP_COLORS.ephemeral.color, 'fill-opacity': 0.15 },
      });

      // Polygon outline
      map.addLayer({
        id: 'ephemeral-result-outline',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Polygon'],
        paint: { 'line-color': MAP_COLORS.ephemeral.color, 'line-width': 2, 'line-dasharray': [3, 2] },
      });

      // Line layer
      map.addLayer({
        id: 'ephemeral-result-line',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'LineString'],
        paint: { 'line-color': MAP_COLORS.ephemeral.color, 'line-width': 2.5, 'line-dasharray': [3, 2] },
      });

      // Point layer
      map.addLayer({
        id: 'ephemeral-result-circle',
        type: 'circle',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': MAP_COLORS.ephemeral.color,
          'circle-stroke-color': MAP_COLORS.ephemeral.outline,
          'circle-stroke-width': 2,
        },
      });

    }

    // Zoom only on the first add for this result; the persistent style.load
    // re-adds below must not re-fit the viewport on every basemap switch.
    let zoomed = false;
    function addLayersAndMaybeZoom() {
      if (!map || !ephemeralResult) return;
      addLayers();
      if (!zoomed) {
        zoomed = true;
        map.fitBounds(toFitBounds(ephemeralResult.bbox), { padding: 40, maxZoom: 18 });
      }
    }

    if (map.isStyleLoaded()) {
      addLayersAndMaybeZoom();
    } else {
      // On the ?chat_result=1 cold-load pickup the dataset-layer sync leaves the
      // style transiently not-loaded after the initial `style.load` has already
      // fired, so the subscription below never fires and the overlay would be
      // dropped (badge shows, map at world view). A one-shot `idle` retries once
      // the map settles, as BuilderMap's layer-sync gate does.
      map.once('idle', addLayersAndMaybeZoom);
    }
    // Subscribe for the lifetime of the result: a basemap/style reload wipes the
    // overlay while the result badge stays, with no re-show path.
    map.on('style.load', addLayersAndMaybeZoom);

    return () => {
      map.off('idle', addLayersAndMaybeZoom);
      map.off('style.load', addLayersAndMaybeZoom);
    };
  }, [ephemeralResult, mapInstanceRef]);

  const handleQueryResult = useCallback((
    geojson: GeoJSON.FeatureCollection,
    bbox: [number, number, number, number],
    meta?: {
      truncated?: boolean;
      totalCount?: number;
      viewportScoped?: boolean;
      analysis?: EphemeralAnalysisHandoff;
      prompt?: string;
      source?: 'analysis-panel';
    },
  ) => {
    setEphemeralResult({ geojson, bbox, ...meta });
  }, []);

  return {
    ephemeralResult,
    handleQueryResult,
    handleDismissEphemeral: clearEphemeralLayer,
  };
}
