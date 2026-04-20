import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';

export const rasterAdapter: LayerAdapter = {
  type: 'raster',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, tileUrl, tileSize, minzoom, maxzoom, opacity, visible } = input;
    if (map.getSource(sourceId)) return;
    map.addSource(sourceId, {
      type: 'raster',
      tiles: [`${window.location.origin}${tileUrl}`],
      tileSize: tileSize ?? 256,
      minzoom: minzoom ?? 0,
      maxzoom: maxzoom ?? 18,
    });
    map.addLayer({
      id: layerId,
      type: 'raster',
      source: sourceId,
      paint: { 'raster-opacity': opacity ?? 1 },
    });
    if (!visible) {
      map.setLayoutProperty(layerId, 'visibility', 'none');
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, opacity, visible } = input;
    if (!map.getLayer(layerId)) return;
    // Raster: sync opacity and visibility only
    const currentOpacity = map.getPaintProperty(layerId, 'raster-opacity');
    if (currentOpacity !== (opacity ?? 1)) {
      map.setPaintProperty(layerId, 'raster-opacity', opacity ?? 1);
    }
    const vis = visible ? 'visible' : 'none';
    if (map.getLayoutProperty(layerId, 'visibility') !== vis) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
