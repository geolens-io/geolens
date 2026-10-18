import type { AdapterLayerInput, ImageSpec, LayerAdapter, LayerDrawing } from './types';
import { filterSpec, sourceLayerSpec } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';
import type { StyleConfig, SymbolStyleConfig } from '@/types/api';
import { DEFAULT_POINT_LABEL_OFFSET, LABEL_FONT_STACK } from '../label-layer-utils';
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';

const DEFAULT_ICON = 'marker';
const GEOLENS_SPRITE_ID = 'geolens';
const GEOLENS_SPRITE_PATH = '/api/maps/sprites/geolens';
// Symbol authoring is a DELIBERATE curated subset: icon
// (image/size/rotate/anchor/offset/allow-overlap), basic label
// (field/size/font/anchor/offset/allow-overlap/max-width) and the paint set
// below. The other ~30 spec symbol properties
// (symbol-placement/spacing/sort-key, icon-text-fit, icon-keep-upright,
// text-justify/transform/letter-spacing/variable-anchor, *-rotation-alignment,
// *-translate, text-halo-blur, etc.) are out of scope. symbolLayout() spreads
// ...input.layout first, so any such stored property survives round-trip
// without an authoring UI.
export const SYMBOL_OWNED_LAYOUT_PROPERTIES = [
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
export const SYMBOL_OWNED_PAINT_PROPERTIES = [
  'icon-opacity',
  'text-color',
  'text-halo-color',
  'text-halo-width',
  'text-opacity',
] as const;

/**
 * Merge a layer's symbol config from the two places it can live.
 * `style_config.builder.symbol` is the legacy stash and `style_config.symbol`
 * the current home; a layer can carry BOTH, with the top-level object winning
 * field by field. Exported because map-sync resolves `categoryColumn` for the
 * tile column list, and picking whichever object exists (instead of merging)
 * would drop a `categoryColumn` stashed under `builder` whenever any top-level
 * symbol object was present.
 */
export function resolveSymbolConfig(
  styleConfig: StyleConfig | null | undefined,
): SymbolStyleConfig {
  const config = styleConfig ?? {};
  const builder = config.builder ?? {};
  return {
    ...(builder.symbol ?? {}),
    ...(config.symbol ?? {}),
  };
}

function getSymbolConfig(input: AdapterLayerInput): SymbolStyleConfig {
  return resolveSymbolConfig(input.style_config);
}

function spriteIconId(icon: string): string {
  return icon.includes(':') ? icon : `${GEOLENS_SPRITE_ID}:${icon}`;
}

const GEOLENS_SPRITE: ImageSpec = { kind: 'sprite', id: GEOLENS_SPRITE_ID, url: GEOLENS_SPRITE_PATH };

function iconImageExpression(symbol: SymbolStyleConfig): string | unknown[] {
  const fallback = symbol.iconImage || DEFAULT_ICON;
  if (!symbol.categoryColumn || !symbol.categories?.length) return spriteIconId(fallback);
  const pairs: unknown[] = [];
  for (const entry of symbol.categories) {
    // Skip null values too: the to-string input below renders null as "", so a
    // null-valued pair could never match.
    if (entry.value === undefined || entry.value === null || !entry.icon) continue;
    pairs.push(String(entry.value), spriteIconId(entry.icon));
  }
  if (pairs.length === 0) {
    // Zero pairs would emit ['match', input, fallback] (length 3 < the spec
    // minimum 5): addLayer throws (swallowed) and the symbol layer silently
    // never renders. Backend export mirrors this guard.
    return spriteIconId(fallback);
  }
  // To-string the input and stringify labels so numeric MVT values match the
  // stringified sample values the editor stores.
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
    // Honor the label overlap toggle for the icon too. Gated on an active label
    // column so a stale allowOverlap from a cleared label config can't hide
    // icons with no visible control. Deliberately EXPLICIT false only: an
    // absent allowOverlap keeps icons overlapping so saved maps that never
    // touched the toggle don't change rendering; text keeps its own ?? false
    // default.
    'icon-allow-overlap': !(lc?.column && lc.allowOverlap === false),
    visibility: input.visible ? 'visible' : 'none',
  };

  if (lc?.column) {
    layout['text-field'] = ['get', lc.column];
    layout['text-size'] = lc.fontSize ?? 12;
    layout['text-font'] = [...LABEL_FONT_STACK];
    // Default anchor/offset must match the companion-label path AND what
    // LabelEditor displays (center / DEFAULT_POINT_LABEL_OFFSET); otherwise the
    // editor would show Center/0/-1.5 while the map draws top/0/1.2 and the
    // first Offset-X drag would snap the text across the point.
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

function describeSymbol(input: AdapterLayerInput): LayerDrawing {
  return {
    specs: [{
      layer: {
        id: input.layerId,
        type: 'symbol',
        source: input.sourceId,
        ...sourceLayerSpec(input),
        ...filterSpec(input.filter),
        layout: symbolLayout(input),
        paint: symbolPaint(input),
      },
      ownedPaint: SYMBOL_OWNED_PAINT_PROPERTIES,
      ownedLayout: SYMBOL_OWNED_LAYOUT_PROPERTIES,
    }],
    images: [GEOLENS_SPRITE],
  };
}

export const symbolAdapter: LayerAdapter = {
  type: 'symbol',
  describe: describeSymbol,

  addLayers(map, input) {
    addDescribedLayer(map, describeSymbol(input));
  },

  syncPaint(map, input) {
    if (!map.getLayer(input.layerId)) return;
    writeDescribedLayer(map, describeSymbol(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeSymbol(input));
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
