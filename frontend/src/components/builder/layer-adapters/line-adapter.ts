import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, filterPaintForLayerType, finalizeLayer, getBuilderStyleConfig, getExpressionSafeOpacity, syncVectorPaint, syncSingleLayerVisibility, syncLayerFilter } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';

const ARROW_IMAGE_ID = 'geolens-line-arrow';
const ARROW_BASE_SIZE = 14;

function arrowLayerId(layerId: string) {
  return `${layerId}-arrow`;
}

function arrowImageData() {
  const size = 24;
  const data = new Uint8ClampedArray(size * size * 4);
  const setPixel = (x: number, y: number, alpha: number) => {
    const index = (y * size + x) * 4;
    data[index] = 255;
    data[index + 1] = 255;
    data[index + 2] = 255;
    data[index + 3] = alpha;
  };

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const inStem = x >= 3 && x <= 13 && y >= 9 && y <= 14;
      const headWidth = Math.max(0, 20 - x);
      const inHead = x >= 10 && x <= 21 && Math.abs(y - 11.5) <= headWidth * 0.55;
      if (inStem || inHead) setPixel(x, y, 255);
    }
  }

  return { width: size, height: size, data };
}

function ensureArrowImage(map: MaplibreMap) {
  try {
    if (map.hasImage?.(ARROW_IMAGE_ID)) return;
    map.addImage(ARROW_IMAGE_ID, arrowImageData(), { sdf: true, pixelRatio: 1 });
  } catch (e) {
    if (import.meta.env.DEV) console.warn('[map-sync] Arrow icon registration failed:', e);
  }
}

function arrowConfig(input: AdapterLayerInput) {
  const builder = getBuilderStyleConfig(input);
  const lineColor = typeof input.paint['line-color'] === 'string'
    ? input.paint['line-color']
    : MAP_COLORS.default.fill;
  return {
    color: typeof builder.arrowColor === 'string' ? builder.arrowColor : lineColor,
    size: typeof builder.arrowSize === 'number' ? builder.arrowSize : 14,
    spacing: typeof builder.arrowSpacing === 'number' ? builder.arrowSpacing : 80,
  };
}

function isArrowMode(input: AdapterLayerInput) {
  return input.style_config?.render_mode === 'arrow';
}

function addArrowLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const { layerId, sourceId, sourceLayer, filter, opacity, visible } = input;
  const id = arrowLayerId(layerId);
  const config = arrowConfig(input);
  if (map.getLayer(id)) return;
  ensureArrowImage(map);

  map.addLayer({
    id,
    type: 'symbol',
    source: sourceId,
    ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
    layout: {
      'symbol-placement': 'line',
      'symbol-spacing': config.spacing,
      'icon-image': ARROW_IMAGE_ID,
      'icon-size': config.size / ARROW_BASE_SIZE,
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
      'icon-rotation-alignment': 'map',
      'visibility': visible ? 'visible' : 'none',
    },
    paint: {
      'icon-color': config.color,
      'icon-opacity': opacity ?? 1,
    },
    ...(filter && Array.isArray(filter) && filter.length > 0 ? { filter } : {}),
  });
}

function syncArrowLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = arrowLayerId(input.layerId);
  if (!isArrowMode(input)) {
    if (map.getLayer(id)) map.removeLayer(id);
    return;
  }
  if (!map.getLayer(id)) {
    addArrowLayer(map, input);
  }
  if (!map.getLayer(id)) return;

  const config = arrowConfig(input);
  map.setLayoutProperty(id, 'symbol-spacing', config.spacing);
  map.setLayoutProperty(id, 'icon-size', config.size / ARROW_BASE_SIZE);
  map.setPaintProperty(id, 'icon-color', config.color);
  map.setPaintProperty(id, 'icon-opacity', input.opacity ?? 1);
  map.setLayoutProperty(id, 'visibility', input.visible ? 'visible' : 'none');
  syncLayerFilter(map, id, input.filter);
}

export const lineAdapter: LayerAdapter = {
  type: 'line',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout: storedLayout, opacity, filter, visible } = input;
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      // line-dasharray is stored in layout JSON but is a MapLibre paint property
      const { 'line-dasharray': dasharray, ...restLayout } = storedLayout;
      const linePaint = filterPaintForLayerType(basePaint, 'line');
      // line-gradient REQUIRES an expression that consumes ['line-progress'] — there is no
      // valid scalar fallback. simplifyPaint flattens arrays to scalar fallbacks (e.g.
      // `interpolate`'s value[4] color stop), which produces a plain string that MapLibre
      // rejects on addLayer. Drop it here and let finalizeLayer's replayExpressions install
      // the real expression after addLayer succeeds. See REVIEW.md WR-02.
      if (hasExpressions && Array.isArray(rawPaint['line-gradient'])) {
        delete linePaint['line-gradient'];
      }
      if (Object.keys(linePaint).length === 0) {
        linePaint['line-color'] = MAP_COLORS.default.fill;
        linePaint['line-width'] = 2;
      }
      if (dasharray) {
        linePaint['line-dasharray'] = dasharray;
      }
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: linePaint,
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          ...restLayout,
          // BUG-01: honor input.visible at initial add — see fill-adapter for rationale.
          ...(visible === false ? { visibility: 'none' as const } : {}),
        },
      });
      finalizeLayer(map, layerId, rawPaint, 'line', opacity ?? 1, filter, hasExpressions);
      if (isArrowMode(input)) {
        addArrowLayer(map, input);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    if (!map.getLayer(layerId)) return;
    syncVectorPaint(map, layerId, rawPaint, 'line');
    map.setPaintProperty(layerId, 'line-opacity', getExpressionSafeOpacity(rawPaint, 'line', opacity ?? 1));
    const dasharray = input.layout?.['line-dasharray'];
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'line-dasharray', dasharray ?? undefined);
    }
    syncLayerFilter(map, layerId, filter);
    syncArrowLayer(map, input);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
    syncSingleLayerVisibility(map, arrowLayerId(input.layerId), input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, arrowLayerId(layerId)];
  },
};
