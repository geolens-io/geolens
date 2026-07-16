import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { syncOwnedLayoutProperties, syncOwnedPaintProperties, syncSingleLayerVisibility, syncLayerFilter } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';
import type { SymbolStyleConfig } from '@/types/api';
import { DEFAULT_POINT_LABEL_OFFSET, LABEL_FONT_STACK } from '../label-layer-utils';

const DEFAULT_ICON = 'marker';
const GEOLENS_SPRITE_ID = 'geolens';
const GEOLENS_SPRITE_PATH = '/api/maps/sprites/geolens';
// builder-audit #338 SPEC-02: symbol authoring is a DELIBERATE curated subset — icon
// (image/size/rotate/anchor/offset/allow-overlap) + basic label (field/size/font/anchor/
// offset/allow-overlap/max-width) and the paint set below. The other ~30 spec symbol
// properties (symbol-placement/spacing/sort-key, icon-text-fit, icon-keep-upright,
// text-justify/transform/letter-spacing/variable-anchor, *-rotation-alignment, *-translate,
// text-halo-blur, etc.) are intentionally out of scope. symbolLayout() spreads ...input.layout
// first, so any such stored property survives round-trip even though it has no authoring UI.
const SYMBOL_OWNED_LAYOUT_PROPERTIES = [
  'icon-image',
  'icon-size',
  'icon-rotate',
  'icon-anchor',
  'icon-offset',
  'icon-allow-overlap',
  'visibility',
  'text-field',
  'text-size',
  'text-font',
  'text-anchor',
  'text-offset',
  'text-allow-overlap',
  'text-max-width',
] as const;
const SYMBOL_OWNED_PAINT_PROPERTIES = [
  'icon-opacity',
  'text-color',
  'text-halo-color',
  'text-halo-width',
  'text-opacity',
] as const;

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

function getGeolensSpriteUrl(): string {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return new URL(GEOLENS_SPRITE_PATH, window.location.origin).toString();
  }
  return GEOLENS_SPRITE_PATH;
}

function ensureGeolensSprite(map: MaplibreMap): void {
  try {
    const sprites = map.getSprite?.() ?? [];
    if (!sprites.some((sprite) => sprite.id === GEOLENS_SPRITE_ID)) {
      map.addSprite(GEOLENS_SPRITE_ID, getGeolensSpriteUrl());
    }
  } catch (e) {
    if (import.meta.env.DEV) console.warn('[map-sync] GeoLens sprite registration failed:', e);
  }
}

function iconImageExpression(symbol: SymbolStyleConfig): string | unknown[] {
  const fallback = symbol.iconImage || DEFAULT_ICON;
  if (!symbol.categoryColumn || !symbol.categories?.length) return spriteIconId(fallback);
  const pairs: unknown[] = [];
  for (const entry of symbol.categories) {
    // fix(#394) ST-04: skip null values too — the to-string input below
    // renders null as "", so a null-valued pair could never match.
    if (entry.value === undefined || entry.value === null || !entry.icon) continue;
    pairs.push(String(entry.value), spriteIconId(entry.icon));
  }
  if (pairs.length === 0) {
    // fix(#394) ST-01: zero pairs would emit ['match', input, fallback]
    // (length 3 < the spec minimum 5) — addLayer throws (swallowed) and the
    // symbol layer silently never renders. Backend export mirrors this guard.
    return spriteIconId(fallback);
  }
  // fix(#394) ST-04: to-string the input and stringify labels so numeric MVT
  // values match the stringified sample values the editor stores (numeric
  // category columns always fell through to the fallback icon before).
  return ['match', ['to-string', ['get', symbol.categoryColumn]], ...pairs, spriteIconId(fallback)];
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
    // fix(#527 B-054/LB-04): honor the label overlap toggle for the icon too —
    // hardcoded true meant "allow overlap: off" decluttered text only. Gated
    // on an active label column so a stale allowOverlap from a cleared label
    // config can't hide icons with no visible control.
    'icon-allow-overlap': !(lc?.column && lc.allowOverlap === false),
    visibility: input.visible ? 'visible' : 'none',
  };

  if (lc?.column) {
    layout['text-field'] = ['get', lc.column];
    layout['text-size'] = lc.fontSize ?? 12;
    layout['text-font'] = [...LABEL_FONT_STACK];
    // fix(#526 B-042): default anchor/offset must match the companion-label
    // path AND what LabelEditor displays (center / DEFAULT_POINT_LABEL_OFFSET).
    // The old 'top'/[0,1.2] defaults meant the editor showed Center/0/-1.5
    // while the map drew top/0/1.2, and the first Offset-X drag snapped the
    // text across the point.
    layout['text-anchor'] = lc.textAnchor ?? 'center';
    layout['text-offset'] = lc.textOffset ?? [...DEFAULT_POINT_LABEL_OFFSET];
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
        syncLayerFilter(map, input.layerId, input.filter);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${input.layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    if (!map.getLayer(input.layerId)) return;
    ensureGeolensSprite(map);
    const layout = symbolLayout(input);
    syncOwnedLayoutProperties(map, input.layerId, layout, {
      ownedProperties: SYMBOL_OWNED_LAYOUT_PROPERTIES,
    });
    const paint = symbolPaint(input);
    syncOwnedPaintProperties(map, input.layerId, paint, {
      ownedProperties: SYMBOL_OWNED_PAINT_PROPERTIES,
    });
    syncLayerFilter(map, input.layerId, input.filter);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
