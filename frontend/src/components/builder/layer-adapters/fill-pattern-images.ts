import type { ImageSpec } from './types';

/** Namespaced ids for the curated built-in fill-pattern set. */
export const FILL_PATTERN_IDS = [
  'geolens-fill-hatch',
  'geolens-fill-crosshatch',
  'geolens-fill-diagonal',
  'geolens-fill-dots',
  'geolens-fill-grid',
] as const;

/** Narrowed string type for programmatic pattern-id validation. Consumers may use this
 *  with `includes`-style guards: `FILL_PATTERN_IDS.includes(value as FillPatternId)`. */
export type FillPatternId = typeof FILL_PATTERN_IDS[number];

/** Shared tile size for all built-in patterns (16×16, seamlessly tileable). */
const TILE = 16;

export type Rgb = readonly [number, number, number];
type PatternImage = { width: number; height: number; data: Uint8ClampedArray };

/** The pre-#914 fixed pattern colour, still used when no tint is resolvable. */
export const DEFAULT_PATTERN_RGB: Rgb = [80, 80, 80];

/** RGBA pixel writer helper: sets a pixel at (x, y) in a TILE×TILE data array. */
function setPixel(data: Uint8ClampedArray, x: number, y: number, r: number, g: number, b: number, a: number) {
  const i = (y * TILE + x) * 4;
  data[i] = r;
  data[i + 1] = g;
  data[i + 2] = b;
  data[i + 3] = a;
}

/** Horizontal hatch lines (every 4 pixels). */
function makeHatch(rgb: Rgb): PatternImage {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      if (y % 4 === 0) {
        setPixel(data, x, y, rgb[0], rgb[1], rgb[2], 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** True diagonal crosshatch: 45-degree lines in both directions (/ and \). */
function makeCrosshatch(rgb: Rgb): PatternImage {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // Forward diagonal (/) and backward diagonal (\), spaced every 4 pixels.
      // `(x - y + TILE * 4) % 4` avoids negative modulo on any JS engine.
      if ((x + y) % 4 === 0 || (x - y + TILE * 4) % 4 === 0) {
        setPixel(data, x, y, rgb[0], rgb[1], rgb[2], 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** 45-degree diagonal lines (bottom-left to top-right, wrapping at tile edge). */
function makeDiagonal(rgb: Rgb): PatternImage {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // Lines appear every 4 pixels along the diagonal; wrap with modulo for seamless tiling
      if ((x + y) % 4 === 0) {
        setPixel(data, x, y, rgb[0], rgb[1], rgb[2], 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** Regular dot grid (dots every 4 pixels, 2×2 dot size). */
function makeDots(rgb: Rgb): PatternImage {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // 2×2 dot at multiples of 4
      if (x % 4 < 2 && y % 4 < 2) {
        setPixel(data, x, y, rgb[0], rgb[1], rgb[2], 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** Grid: 1px lines at every 4 pixels on both axes. */
function makeGrid(rgb: Rgb): PatternImage {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      if (x % 4 === 0 || y % 4 === 0) {
        setPixel(data, x, y, rgb[0], rgb[1], rgb[2], 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

const GENERATORS: Record<string, (rgb: Rgb) => PatternImage> = {
  'geolens-fill-hatch': makeHatch,
  'geolens-fill-crosshatch': makeCrosshatch,
  'geolens-fill-diagonal': makeDiagonal,
  'geolens-fill-dots': makeDots,
  'geolens-fill-grid': makeGrid,
};

/** Generate the ImageData-like object for a given fill pattern id. */
export function makeFillPatternImage(id: string, rgb: Rgb = DEFAULT_PATTERN_RGB): PatternImage {
  const gen = GENERATORS[id];
  if (!gen) throw new Error(`[fill-pattern-images] Unknown pattern id: ${id}`);
  return gen(rgb);
}

/** The built-in patterns as images the writer registers. They are full-colour tiles, so not SDF icons. */
export const FILL_PATTERN_IMAGES: readonly ImageSpec[] = FILL_PATTERN_IDS.map((id) => ({
  kind: 'image',
  id,
  data: () => makeFillPatternImage(id),
}));

/**
 * The image for a built-in pattern drawn in `color`, or null when the pattern
 * stays plain: no tint, a colour that is not hex, or an id that is not built in.
 *
 * The image id is a MapLibre registry key, never a style value. Saved paint, the
 * wire format and exported style.json all keep the plain `geolens-fill-*` id; a
 * tinted id names an image that exists only in the session that drew the layer.
 */
export function tintedFillPattern(id: string, color: string | undefined): ImageSpec | null {
  if (!GENERATORS[id] || !color) return null;
  const rgb = hexToRgb(color);
  if (!rgb) return null;
  return { kind: 'image', id: tintedFillPatternId(id, rgb), data: () => makeFillPatternImage(id, rgb) };
}

/** `geolens-fill-hatch#1d4ed8` — normalised so `#1D4ED8` and `#1d4ed8` share a tile. */
function tintedFillPatternId(id: string, rgb: Rgb): string {
  const hex = rgb.map((c) => c.toString(16).padStart(2, '0')).join('');
  return `${id}#${hex}`;
}

/**
 * Strict 6- or 3-digit hex to RGB. Deliberately narrow: every colour the builder
 * writes is `#rrggbb` (MAP_COLORS and react-colorful both), and anything else
 * falls back to the untinted tile rather than guessing.
 */
function hexToRgb(color: string): Rgb | null {
  const m = /^#([0-9a-f]{6}|[0-9a-f]{3})$/i.exec(color.trim());
  if (!m) return null;
  const hex = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
  ];
}
