import type { StyleSpecification } from 'maplibre-gl';
import type { BasemapEntry } from '@/api/settings';
import type {
  MapBasemapConfig,
  MapBasemapLandWaterTone,
  MapBasemapReliefContrast,
  MapBasemapVisibilityMode,
} from '@/types/api';
import positronThumb from '@/assets/basemaps/positron.png';
import darkThumb from '@/assets/basemaps/dark.png';
import osmThumb from '@/assets/basemaps/osm.png';
import brightThumb from '@/assets/basemaps/bright.png';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';

export const LIGHT_PRESET_ID = 'openfreemap-positron';
export const DARK_PRESET_ID = 'openfreemap-dark';
export const BLANK_BASEMAP_ID = 'blank';

export const DEFAULT_BASEMAP_CONFIG: MapBasemapConfig = {
  label_mode: 'full',
  road_visibility: 'full',
  boundary_visibility: 'full',
  building_visibility: true,
  land_water_tone: 'default',
  relief_contrast: null,
  opacity: 1,
};

const VISIBILITY_MODES = new Set<MapBasemapVisibilityMode>(['full', 'subtle', 'hidden']);
const LAND_WATER_TONES = new Set<MapBasemapLandWaterTone>(['default', 'muted', 'contrast', 'monochrome']);
const RELIEF_CONTRASTS = new Set<MapBasemapReliefContrast>(['soft', 'standard', 'strong']);

export type StyleLayer = StyleSpecification['layers'][number] & {
  id: string;
  type?: string;
  source?: unknown;
  'source-layer'?: unknown;
  paint?: Record<string, unknown>;
  layout?: Record<string, unknown>;
};

const ROAD_PATTERNS = [
  'road',
  'street',
  'highway',
  'motorway',
  'trunk',
  'primary',
  'secondary',
  'tertiary',
  'path',
  'rail',
  'transit',
  'transport',
];
const BOUNDARY_PATTERNS = ['boundary', 'admin', 'country', 'state', 'province'];
const BUILDING_PATTERNS = ['building', 'extrusion'];
const WATER_PATTERNS = ['water', 'river', 'lake', 'ocean'];
const LAND_PATTERNS = ['land', 'earth', 'park', 'wood', 'forest', 'natural', 'greenspace'];

const LAND_WATER_PALETTE: Record<
  Exclude<MapBasemapLandWaterTone, 'default'>,
  { land: string; water: string; park: string }
> = {
  muted: { land: '#f1f0ea', water: '#d8e5e8', park: '#dee7d8' },
  contrast: { land: '#f4ead4', water: '#8fb8d8', park: '#b8d5a5' },
  monochrome: { land: '#f2f2f0', water: '#d9dde0', park: '#e5e5df' },
};

const RELIEF_PALETTE: Record<
  MapBasemapReliefContrast,
  { exaggeration: number; shadow: string; highlight: string }
> = {
  soft: { exaggeration: 0.35, shadow: '#8d969c', highlight: '#ffffff' },
  standard: { exaggeration: 0.55, shadow: '#6f7b83', highlight: '#ffffff' },
  strong: { exaggeration: 0.85, shadow: '#47545c', highlight: '#ffffff' },
};

/** Fallback glyphs for inline styles (raster basemaps) so text labels render. */
const FALLBACK_GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';

const BLANK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#f3f4f6" width="160" height="160" rx="8" stroke="#d1d5db" stroke-width="2" stroke-dasharray="8 4"/>' +
  '<line x1="30" y1="30" x2="130" y2="130" stroke="#9ca3af" stroke-width="3" stroke-linecap="round"/>' +
  '<text x="80" y="148" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="system-ui,sans-serif">None</text>' +
  '</svg>'
)}`;

const BUILTIN_THUMBNAILS: Record<string, string> = {
  'blank': BLANK_THUMBNAIL,
  'openfreemap-positron': positronThumb,
  'openfreemap-dark': darkThumb,
  'openstreetmap': osmThumb,
  'osm-standard': osmThumb,
  'openfreemap-bright': brightThumb,
};

const FALLBACK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#e5e7eb" width="160" height="160" rx="8"/>' +
  '<circle cx="80" cy="72" r="36" fill="none" stroke="#9ca3af" stroke-width="2"/>' +
  '<ellipse cx="80" cy="72" rx="16" ry="36" fill="none" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="44" y1="72" x2="116" y2="72" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="80" y1="36" x2="80" y2="108" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<text x="80" y="136" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="system-ui,sans-serif">Map</text>' +
  '</svg>'
)}`;

const MISSING_REMOTE_STYLE_IMAGES = new Set(['circle-11', 'wood-pattern', 'road_', 'us-state_']);

export function isKnownMissingRemoteStyleImage(id: string): boolean {
  return MISSING_REMOTE_STYLE_IMAGES.has(id);
}

/** Get the thumbnail URL for a basemap, with a fallback globe icon for custom basemaps */
export function basemapThumbnail(id: string): string {
  return BUILTIN_THUMBNAILS[id] ?? FALLBACK_THUMBNAIL;
}

const LEGACY_KEY_MAP: Record<string, string> = {
  positron: 'openfreemap-positron',
  'dark-matter': 'openfreemap-dark',
  voyager: 'openfreemap-positron',
  'carto-positron': 'openfreemap-positron',
  'carto-dark-matter': 'openfreemap-dark',
};

/**
 * Convert a basemap URL to a MapLibre style.
 * - If the URL ends with `.json`, it's already a GL style JSON URL -- return as-is.
 *   (GL style JSON basemaps carry their own attribution in the style spec.)
 * - Otherwise (XYZ raster tile URL), wrap it in an inline StyleSpecification.
 *   If attribution is provided, it is set on the raster source so that
 *   MapLibre's AttributionControl displays it.
 */
export function toMaplibreStyle(url: string, attribution?: string): string | StyleSpecification {
  if (url === BLANK_BASEMAP_ID) {
    // No glyphs property — blank basemap has zero symbol/text layers so no
    // glyph fetch is needed. Omitting prevents any glyph request attempts.
    return {
      version: 8 as const,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background' as const,
          paint: { 'background-color': 'rgba(0,0,0,0)' },
        },
      ],
    };
  }
  const urlPath = url.split('?')[0];
  if (urlPath.endsWith('.json') || url.includes('/styles/')) {
    return url;
  }
  return {
    version: 8 as const,
    sources: {
      basemap: {
        type: 'raster' as const,
        tiles: [url],
        tileSize: 256,
        ...(attribution ? { attribution } : {}),
      },
    },
    layers: [{ id: 'basemap-tiles', type: 'raster' as const, source: 'basemap' }],
    glyphs: FALLBACK_GLYPHS,
  };
}

function validVisibilityMode(value: unknown, fallback: MapBasemapVisibilityMode) {
  return typeof value === 'string' && VISIBILITY_MODES.has(value as MapBasemapVisibilityMode)
    ? value as MapBasemapVisibilityMode
    : fallback;
}

function validLandWaterTone(value: unknown) {
  return typeof value === 'string' && LAND_WATER_TONES.has(value as MapBasemapLandWaterTone)
    ? value as MapBasemapLandWaterTone
    : DEFAULT_BASEMAP_CONFIG.land_water_tone;
}

function validReliefContrast(value: unknown) {
  if (value == null) return null;
  return typeof value === 'string' && RELIEF_CONTRASTS.has(value as MapBasemapReliefContrast)
    ? value as MapBasemapReliefContrast
    : null;
}

export function normalizeBasemapConfig(
  value: Partial<MapBasemapConfig> | null | undefined,
  showBasemapLabels = true,
): MapBasemapConfig {
  const labelFallback = showBasemapLabels ? DEFAULT_BASEMAP_CONFIG.label_mode : 'hidden';
  return {
    label_mode: validVisibilityMode(value?.label_mode, labelFallback),
    road_visibility: validVisibilityMode(
      value?.road_visibility,
      DEFAULT_BASEMAP_CONFIG.road_visibility,
    ),
    boundary_visibility: validVisibilityMode(
      value?.boundary_visibility,
      DEFAULT_BASEMAP_CONFIG.boundary_visibility,
    ),
    building_visibility: typeof value?.building_visibility === 'boolean'
      ? value.building_visibility
      : DEFAULT_BASEMAP_CONFIG.building_visibility,
    land_water_tone: validLandWaterTone(value?.land_water_tone),
    relief_contrast: validReliefContrast(value?.relief_contrast),
    opacity:
      typeof value?.opacity === 'number'
      && Number.isFinite(value.opacity)
      && value.opacity >= 0
      && value.opacity <= 1
        ? value.opacity
        : DEFAULT_BASEMAP_CONFIG.opacity,
  };
}

function layerTokens(layer: StyleLayer) {
  return [
    layer.id,
    typeof layer.source === 'string' ? layer.source : '',
    typeof layer['source-layer'] === 'string' ? layer['source-layer'] : '',
  ].join(' ').toLowerCase();
}

function matchesAny(layer: StyleLayer, patterns: string[]) {
  const tokens = layerTokens(layer);
  return patterns.some((pattern) => tokens.includes(pattern));
}

export function isTextLabelLayer(layer: StyleLayer) {
  if (layer.type !== 'symbol') return false;
  const layout = layer.layout ?? {};
  return layout['text-field'] != null || layerTokens(layer).includes('label');
}

export function isRoadLayer(layer: StyleLayer) {
  return (layer.type === 'line' || layer.type === 'symbol') && matchesAny(layer, ROAD_PATTERNS);
}

export function isBoundaryLayer(layer: StyleLayer) {
  return (layer.type === 'line' || layer.type === 'symbol') && matchesAny(layer, BOUNDARY_PATTERNS);
}

export function isBuildingLayer(layer: StyleLayer) {
  return layer.type === 'fill-extrusion' || matchesAny(layer, BUILDING_PATTERNS);
}

/** Phase 1059 BSE-01: semantic sublayer ID → MapLibre style-layer predicate map.
 *  Used by `applySublayerOverrides` (frontend/src/lib/builder/basemap-style-mutation.ts)
 *  to resolve a sublayer override key ('road') to the set of actual style layers
 *  it applies to. Open key set — new sublayer IDs are added here. */
export const SUBLAYER_CLASSIFIERS: Record<string, (layer: StyleLayer) => boolean> = {
  road: isRoadLayer,
  boundary: isBoundaryLayer,
  building: isBuildingLayer,
  label: isTextLabelLayer,
};

function isWaterLayer(layer: StyleLayer) {
  return matchesAny(layer, WATER_PATTERNS);
}

function isParkLayer(layer: StyleLayer) {
  return matchesAny(layer, ['park', 'wood', 'forest', 'natural', 'greenspace']);
}

function isLandLayer(layer: StyleLayer) {
  return layer.type === 'background' || matchesAny(layer, LAND_PATTERNS);
}

function withLayout(layer: StyleLayer, layout: Record<string, unknown>) {
  return { ...layer, layout: { ...(layer.layout ?? {}), ...layout } };
}

function withPaint(layer: StyleLayer, paint: Record<string, unknown>) {
  return { ...layer, paint: { ...(layer.paint ?? {}), ...paint } };
}

function withVisibility(layer: StyleLayer, visible: boolean) {
  return withLayout(layer, { visibility: visible ? 'visible' : 'none' });
}

function applyProminence(
  layer: StyleLayer,
  mode: MapBasemapVisibilityMode,
  subtlePaint: Record<string, unknown>,
) {
  if (mode === 'hidden') return withVisibility(layer, false);
  const visibleLayer = withVisibility(layer, true);
  return mode === 'subtle' ? withPaint(visibleLayer, subtlePaint) : visibleLayer;
}

function applyLandWaterTone(layer: StyleLayer, tone: MapBasemapLandWaterTone) {
  if (tone === 'default') return layer;
  const palette = LAND_WATER_PALETTE[tone];
  if (layer.type === 'background') {
    return withPaint(layer, { 'background-color': palette.land });
  }
  if (layer.type !== 'fill') return layer;
  if (isWaterLayer(layer)) return withPaint(layer, { 'fill-color': palette.water });
  if (isParkLayer(layer)) return withPaint(layer, { 'fill-color': palette.park });
  if (isLandLayer(layer)) return withPaint(layer, { 'fill-color': palette.land });
  return layer;
}

function applyReliefContrast(
  layer: StyleLayer,
  reliefContrast: MapBasemapReliefContrast | null | undefined,
) {
  if (!reliefContrast || layer.type !== 'hillshade') return layer;
  const palette = RELIEF_PALETTE[reliefContrast];
  return withPaint(layer, {
    'hillshade-exaggeration': palette.exaggeration,
    'hillshade-shadow-color': palette.shadow,
    'hillshade-highlight-color': palette.highlight,
  });
}

// Multiplicative opacity keys MapLibre exposes on the layer paint surface.
// Keep this set narrow: only canonical *-opacity scalars MapLibre treats
// as numeric. Expression values (arrays/objects) and non-number scalars
// are left untouched.
const OPACITY_PAINT_KEYS_BY_TYPE: Record<string, readonly string[]> = {
  raster: ['raster-opacity'],
  fill: ['fill-opacity'],
  'fill-extrusion': ['fill-extrusion-opacity'],
  line: ['line-opacity'],
  symbol: ['text-opacity', 'icon-opacity'],
  circle: ['circle-opacity', 'circle-stroke-opacity'],
  heatmap: ['heatmap-opacity'],
};

// CR-01 fix (quick-260516-9g9 followup): write absolute master-opacity values,
// composed with prominence stamps applied earlier in the same call.
//
// Previous design read `existingPaint[key]` and multiplied — but when
// applyBasemapConfigToMap feeds map.getStyle() (live, post-mutation) as input,
// `existing` already contains a prior master-opacity stamp. Compounding occurs
// and masterOpacity >= 1 short-circuits the reset, leaving the slider monotonic-
// downward (review finding CR-01).
//
// Fix: never read live paint. The `prominenceStamps` map tells us which keys
// applyProminence set this call (with the canonical subtle values). Other keys
// default to 1.0 (MapLibre default). We always write `stamp * master` or
// `master`, so the next setPaintProperty diff correctly restores values when
// the slider returns to 1.0.
function applyMasterOpacity(
  layer: StyleLayer,
  masterOpacity: number,
  prominenceStamps: Record<string, number> = {},
): StyleLayer {
  if (!Number.isFinite(masterOpacity) || masterOpacity < 0) return layer;
  const type = typeof layer.type === 'string' ? layer.type : '';
  const keys = OPACITY_PAINT_KEYS_BY_TYPE[type];
  if (!keys || keys.length === 0) return layer;
  const existingPaint = (layer.paint ?? {}) as Record<string, unknown>;
  const nextPaint: Record<string, unknown> = { ...existingPaint };
  for (const key of keys) {
    const stamp = prominenceStamps[key];
    if (typeof stamp === 'number' && Number.isFinite(stamp)) {
      // applyProminence stamped this key this call — compose against the
      // fresh stamp (not the possibly-stale live paint).
      nextPaint[key] = stamp * masterOpacity;
    } else {
      const existing = existingPaint[key];
      // Expression / non-number existing values: leave untouched (safest —
      // multiplying into an interpolate/step expression requires AST surgery).
      if (existing != null && typeof existing !== 'number') continue;
      // Numeric or absent: write absolute master (MapLibre default is 1.0).
      // This guarantees the slider is reversible — at master=1 we write 1.0,
      // not skip, so the diff loop in map-sync resets any prior compounded
      // value back to default.
      nextPaint[key] = masterOpacity;
    }
  }
  return { ...layer, paint: nextPaint } as StyleLayer;
}

function applyBasemapLayerConfig(
  layer: StyleLayer,
  config: MapBasemapConfig,
): StyleLayer {
  let next = applyLandWaterTone(layer, config.land_water_tone);
  next = applyReliefContrast(next, config.relief_contrast);

  if (isBuildingLayer(next)) {
    next = withVisibility(next, config.building_visibility);
  }
  // Track which paint keys applyProminence stamped this call so applyMasterOpacity
  // can compose against the canonical subtle values rather than live-mutated paint
  // (CR-01 fix — prevents compound stamping on raster + full-mode vector layers).
  // Only `subtle` mode stamps paint; `hidden` writes layout.visibility and `full`
  // is a no-op on paint, so prominenceStamps stays empty in those cases.
  const prominenceStamps: Record<string, number> = {};
  const roadLayer = isRoadLayer(next);
  const boundaryLayer = isBoundaryLayer(next);
  if (roadLayer) {
    const subtle = next.type === 'line'
      ? { 'line-opacity': 0.35 }
      : { 'text-opacity': 0.45, 'icon-opacity': 0.35 };
    next = applyProminence(next, config.road_visibility, subtle);
    if (config.road_visibility === 'subtle') Object.assign(prominenceStamps, subtle);
  }
  if (boundaryLayer) {
    const subtle = next.type === 'line'
      ? { 'line-opacity': 0.4 }
      : { 'text-opacity': 0.45, 'icon-opacity': 0.45 };
    next = applyProminence(next, config.boundary_visibility, subtle);
    if (config.boundary_visibility === 'subtle') Object.assign(prominenceStamps, subtle);
  }
  const sublayerHidden =
    (roadLayer && config.road_visibility === 'hidden') ||
    (boundaryLayer && config.boundary_visibility === 'hidden');
  if (isTextLabelLayer(next) && !sublayerHidden) {
    const subtle = {
      'text-opacity': 0.55,
      'icon-opacity': 0.45,
      'text-halo-width': 0.8,
    };
    next = applyProminence(next, config.label_mode, subtle);
    if (config.label_mode === 'subtle') Object.assign(prominenceStamps, subtle);
  }

  // Path R (quick-260516-9g9): master-opacity applied LAST so it composes on
  // top of per-sublayer prominence stamps. applyMasterOpacity writes absolute
  // values (stamp * master, or master if no stamp) — the previous multiplicative
  // approach compounded on re-entry (CR-01). config.opacity is optional on
  // MapBasemapConfig but always set by normalizeBasemapConfig.
  next = applyMasterOpacity(next, config.opacity ?? 1, prominenceStamps);

  return next;
}

export function applyBasemapConfigToStyle(
  style: StyleSpecification,
  value: Partial<MapBasemapConfig> | null | undefined,
  showBasemapLabels = true,
): StyleSpecification {
  const config = normalizeBasemapConfig(value, showBasemapLabels);
  return {
    ...style,
    layers: style.layers.map((layer) =>
      applyBasemapLayerConfig(layer as StyleLayer, config) as StyleSpecification['layers'][number],
    ) as StyleSpecification['layers'],
  };
}

function expressionReadsColumn(value: unknown, column: string): boolean {
  if (!Array.isArray(value)) return false;
  if (value[0] === 'get' && value[1] === column) return true;
  return value.some((entry) => expressionReadsColumn(entry, column));
}

function hasMissingStyleImageReference(value: unknown): boolean {
  if (typeof value === 'string') {
    return isKnownMissingRemoteStyleImage(value);
  }
  if (Array.isArray(value)) {
    if (value.some((entry) => hasMissingStyleImageReference(entry))) return true;
    return value[0] === 'concat'
      && value.includes('_')
      && expressionReadsColumn(value, 'network');
  }
  return false;
}

function stripMissingStyleImage(value: unknown): unknown {
  if (hasMissingStyleImageReference(value)) return '';
  return value;
}

export function sanitizeMaplibreStyle(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers.map((layer) => {
      let nextLayer = layer as StyleSpecification['layers'][number];
      if ('paint' in nextLayer && nextLayer.paint && 'fill-pattern' in nextLayer.paint) {
        const paint = { ...(nextLayer.paint as Record<string, unknown>) };
        delete paint['fill-pattern'];
        nextLayer = { ...nextLayer, paint } as StyleSpecification['layers'][number];
      }

      if ('layout' in nextLayer && nextLayer.layout && 'icon-image' in nextLayer.layout) {
        nextLayer = {
          ...nextLayer,
          layout: {
            ...nextLayer.layout,
            'icon-image': stripMissingStyleImage(
              (nextLayer.layout as Record<string, unknown>)['icon-image'],
            ),
          },
        } as StyleSpecification['layers'][number];
      }

      if ('filter' in nextLayer && nextLayer.filter) {
        nextLayer = {
          ...nextLayer,
          filter: sanitizeNullableNumericFilter(nextLayer.filter),
        } as StyleSpecification['layers'][number];
      }

      return nextLayer;
    }) as StyleSpecification['layers'],
  };
}

/**
 * Map old saved basemap keys (positron, dark-matter, voyager) to new preset IDs.
 * Returns the key as-is if it's not a legacy key.
 */
export function resolveBasemapId(key: string): string {
  return LEGACY_KEY_MAP[key] ?? key;
}

/**
 * Find the appropriate basemap for the current theme.
 * Prefers DARK_PRESET_ID for dark theme and LIGHT_PRESET_ID for light theme.
 * Falls back to the first enabled basemap.
 */
export function getThemeBasemap(
  basemaps: BasemapEntry[],
  resolvedTheme: 'dark' | 'light',
): BasemapEntry | undefined {
  const enabled = basemaps.filter((b) => b.enabled);
  const targetId = resolvedTheme === 'dark' ? DARK_PRESET_ID : LIGHT_PRESET_ID;
  return enabled.find((b) => b.id === targetId) ?? enabled[0];
}

/**
 * Find a basemap by ID, also checking the legacy key mapping.
 */
export function findBasemapById(
  basemaps: BasemapEntry[],
  id: string,
): BasemapEntry | undefined {
  return basemaps.find((b) => b.id === id) ?? basemaps.find((b) => b.id === resolveBasemapId(id));
}
