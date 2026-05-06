import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { syncSingleLayerVisibility } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';
import type { SymbolStyleConfig } from '@/types/api';

const DEFAULT_ICON = 'marker';
const GEOLENS_SPRITE_ID = 'geolens';
const GEOLENS_SPRITE_URL = '/maps/sprites/geolens';

function getSymbolConfig(input: AdapterLayerInput): SymbolStyleConfig {
  const styleConfig = input.style_config ?? {};
  const builder = styleConfig.builder ?? {};
  return {
    ...(builder.symbol ?? {}),
    ...(styleConfig.symbol ?? {}),
  };
}

function spriteIconId(icon: string): string {
  return icon.includes(':') ? icon : `${GEOLENS_SPRITE_ID}:${icon}`;
}

function ensureGeolensSprite(map: MaplibreMap): void {
  try {
    const sprites = map.getSprite?.() ?? [];
    if (!sprites.some((sprite) => sprite.id === GEOLENS_SPRITE_ID)) {
      map.addSprite(GEOLENS_SPRITE_ID, GEOLENS_SPRITE_URL);
    }
  } catch (e) {
    if (import.meta.env.DEV) console.warn('[map-sync] GeoLens sprite registration failed:', e);
  }
}

function iconImageExpression(symbol: SymbolStyleConfig): string | unknown[] {
  const fallback = symbol.iconImage || DEFAULT_ICON;
  if (!symbol.categoryColumn || !symbol.categories?.length) return spriteIconId(fallback);
  const expression: unknown[] = ['match', ['get', symbol.categoryColumn]];
  for (const entry of symbol.categories) {
    if (entry.value === undefined || !entry.icon) continue;
    expression.push(entry.value, spriteIconId(entry.icon));
  }
  expression.push(spriteIconId(fallback));
  return expression;
}

function symbolLayout(input: AdapterLayerInput): Record<string, unknown> {
  const symbol = getSymbolConfig(input);
  const lc = input.label_config;
  const layout: Record<string, unknown> = {
    ...input.layout,
    'icon-image': iconImageExpression(symbol),
    'icon-size': symbol.iconSize ?? 1,
    'icon-rotate': symbol.iconRotation ?? 0,
    'icon-anchor': symbol.iconAnchor ?? 'center',
    'icon-offset': symbol.iconOffset ?? [0, 0],
    'icon-allow-overlap': true,
    visibility: input.visible ? 'visible' : 'none',
  };

  if (lc?.column) {
    layout['text-field'] = ['get', lc.column];
    layout['text-size'] = lc.fontSize ?? 12;
    layout['text-font'] = ['Noto Sans Regular'];
    layout['text-anchor'] = lc.textAnchor ?? 'top';
    layout['text-offset'] = lc.textOffset ?? [0, 1.2];
    layout['text-allow-overlap'] = lc.allowOverlap ?? false;
    layout['text-max-width'] = 10;
  }

  return layout;
}

function symbolPaint(input: AdapterLayerInput): Record<string, unknown> {
  const lc = input.label_config;
  return {
    'icon-opacity': input.opacity ?? 1,
    ...(lc?.column ? {
      'text-color': lc.textColor ?? MAP_COLORS.label.color,
      'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
      'text-halo-width': lc.haloWidth ?? 1.5,
      'text-opacity': lc.textOpacity ?? 1,
    } : {}),
  };
}

export const symbolAdapter: LayerAdapter = {
  type: 'symbol',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    try {
      ensureGeolensSprite(map);
      map.addLayer({
        id: input.layerId,
        type: 'symbol',
        source: input.sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': input.sourceLayer }),
        layout: symbolLayout(input),
        paint: symbolPaint(input),
      });
      if (input.filter && Array.isArray(input.filter) && input.filter.length > 0) {
        map.setFilter(input.layerId, input.filter);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${input.layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    if (!map.getLayer(input.layerId)) return;
    ensureGeolensSprite(map);
    const layout = symbolLayout(input);
    for (const [key, value] of Object.entries(layout)) {
      map.setLayoutProperty(input.layerId, key, value);
    }
    const paint = symbolPaint(input);
    for (const [key, value] of Object.entries(paint)) {
      map.setPaintProperty(input.layerId, key, value);
    }
    map.setFilter(input.layerId, input.filter ?? null);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
