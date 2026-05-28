import type { Map as MaplibreMap } from 'maplibre-gl';

/** Namespaced ids for the curated built-in fill-pattern set. */
export const FILL_PATTERN_IDS = [
  'geolens-fill-hatch',
  'geolens-fill-crosshatch',
  'geolens-fill-diagonal',
  'geolens-fill-dots',
  'geolens-fill-grid',
] as const;

export type FillPatternId = typeof FILL_PATTERN_IDS[number];

/** Shared tile size for all built-in patterns (16×16, seamlessly tileable). */
const TILE = 16;

/** RGBA pixel writer helper: sets a pixel at (x, y) in a TILE×TILE data array. */
function setPixel(data: Uint8ClampedArray, x: number, y: number, r: number, g: number, b: number, a: number) {
  const i = (y * TILE + x) * 4;
  data[i] = r;
  data[i + 1] = g;
  data[i + 2] = b;
  data[i + 3] = a;
}

/** Horizontal hatch lines (every 4 pixels). */
function makeHatch(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      if (y % 4 === 0) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** Horizontal + vertical hatch (cross-hatch). */
function makeCrosshatch(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      if (y % 4 === 0 || x % 4 === 0) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** 45-degree diagonal lines (bottom-left to top-right, wrapping at tile edge). */
function makeDiagonal(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // Lines appear every 4 pixels along the diagonal; wrap with modulo for seamless tiling
      if ((x + y) % 4 === 0) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** Regular dot grid (dots every 4 pixels, 2×2 dot size). */
function makeDots(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // 2×2 dot at multiples of 4
      if (x % 4 < 2 && y % 4 < 2) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

/** Grid: 1px lines at every 4 pixels on both axes. */
function makeGrid(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      if (x % 4 === 0 || y % 4 === 0) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}

const GENERATORS: Record<string, () => { width: number; height: number; data: Uint8ClampedArray }> = {
  'geolens-fill-hatch': makeHatch,
  'geolens-fill-crosshatch': makeCrosshatch,
  'geolens-fill-diagonal': makeDiagonal,
  'geolens-fill-dots': makeDots,
  'geolens-fill-grid': makeGrid,
};

/** Generate the ImageData-like object for a given fill pattern id. */
export function makeFillPatternImage(id: string): { width: number; height: number; data: Uint8ClampedArray } {
  const gen = GENERATORS[id];
  if (!gen) throw new Error(`[fill-pattern-images] Unknown pattern id: ${id}`);
  return gen();
}

/**
 * Idempotently register all built-in fill-pattern images in the MapLibre image registry.
 * Mirrors ensureArrowImage in line-adapter.ts — skips ids already present, wraps in try/catch.
 * Patterns are full-color tiles: do NOT use sdf:true.
 */
export function ensureFillPatternImages(map: MaplibreMap): void {
  for (const id of FILL_PATTERN_IDS) {
    try {
      if (map.hasImage?.(id)) continue;
      map.addImage(id, makeFillPatternImage(id));
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[map-sync] Fill pattern registration failed:', e);
    }
  }
}
