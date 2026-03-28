import { fillAdapter } from './fill-adapter';
import { lineAdapter } from './line-adapter';
import { circleAdapter } from './circle-adapter';
import { rasterAdapter } from './raster-adapter';
import type { LayerAdapter } from './types';

const adapters: Record<string, LayerAdapter> = {
  fill: fillAdapter,
  line: lineAdapter,
  circle: circleAdapter,
  raster: rasterAdapter,
};

export function getAdapter(type: string): LayerAdapter {
  const adapter = adapters[type];
  if (!adapter) throw new Error(`No adapter for layer type: ${type}`);
  return adapter;
}
