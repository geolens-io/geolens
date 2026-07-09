import { fillAdapter } from './fill-adapter';
import { lineAdapter } from './line-adapter';
import { circleAdapter } from './circle-adapter';
import { rasterAdapter } from './raster-adapter';
import { hillshadeAdapter } from './hillshade-adapter';
import { heatmapAdapter } from './heatmap-adapter';
import { symbolAdapter } from './symbol-adapter';
import { clusterAdapter } from './cluster-adapter';
import { mixedAdapter } from './mixed-adapter';
import type { LayerAdapter } from './types';

const adapters: Record<string, LayerAdapter> = {
  fill: fillAdapter,
  line: lineAdapter,
  circle: circleAdapter,
  symbol: symbolAdapter,
  raster: rasterAdapter,
  hillshade: hillshadeAdapter,
  heatmap: heatmapAdapter,
  cluster: clusterAdapter,
  mixed: mixedAdapter,
};

export function getAdapter(type: string): LayerAdapter {
  const adapter = adapters[type];
  if (!adapter) {
    // B-029: warn unconditionally (not only in DEV) so production also surfaces
    // an unmapped render mode, while keeping the safe circle fallback rather
    // than throwing and breaking the whole map render.
    console.warn(`[registry] Unknown adapter type: ${type}, falling back to circle`);
    return circleAdapter;
  }
  return adapter;
}
