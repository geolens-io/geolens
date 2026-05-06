import { fillAdapter } from './fill-adapter';
import { lineAdapter } from './line-adapter';
import { circleAdapter } from './circle-adapter';
import { rasterAdapter } from './raster-adapter';
import { hillshadeAdapter } from './hillshade-adapter';
import { heatmapAdapter } from './heatmap-adapter';
import { symbolAdapter } from './symbol-adapter';
import type { LayerAdapter } from './types';

const adapters: Record<string, LayerAdapter> = {
  fill: fillAdapter,
  line: lineAdapter,
  circle: circleAdapter,
  symbol: symbolAdapter,
  raster: rasterAdapter,
  hillshade: hillshadeAdapter,
  heatmap: heatmapAdapter,
};

export function getAdapter(type: string): LayerAdapter {
  const adapter = adapters[type];
  if (!adapter) {
    if (import.meta.env.DEV) console.warn(`[registry] Unknown adapter type: ${type}, falling back to circle`);
    return circleAdapter;
  }
  return adapter;
}
