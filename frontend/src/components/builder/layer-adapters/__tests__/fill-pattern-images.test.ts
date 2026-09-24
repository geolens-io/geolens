import { describe, it, expect } from 'vitest';
import {
  FILL_PATTERN_IDS,
  FILL_PATTERN_IMAGES,
  makeFillPatternImage,
  tintedFillPattern,
} from '../fill-pattern-images';

// ──────────────────────────────────────────────────────────────────────────────
describe('FILL_PATTERN_IDS', () => {
  it('is non-empty', () => {
    expect(FILL_PATTERN_IDS.length).toBeGreaterThan(0);
  });

  it('contains at least 5 entries', () => {
    expect(FILL_PATTERN_IDS.length).toBeGreaterThanOrEqual(5);
  });

  it('all ids are unique', () => {
    const set = new Set(FILL_PATTERN_IDS);
    expect(set.size).toBe(FILL_PATTERN_IDS.length);
  });

  it('all ids start with the geolens-fill- prefix', () => {
    for (const id of FILL_PATTERN_IDS) {
      expect(id).toMatch(/^geolens-fill-/);
    }
  });

  it('includes the five curated patterns: hatch, crosshatch, diagonal, dots, grid', () => {
    const ids = new Set(FILL_PATTERN_IDS);
    expect(ids.has('geolens-fill-hatch')).toBe(true);
    expect(ids.has('geolens-fill-crosshatch')).toBe(true);
    expect(ids.has('geolens-fill-diagonal')).toBe(true);
    expect(ids.has('geolens-fill-dots')).toBe(true);
    expect(ids.has('geolens-fill-grid')).toBe(true);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('makeFillPatternImage', () => {
  it('returns an object with finite width and height for every id', () => {
    for (const id of FILL_PATTERN_IDS) {
      const img = makeFillPatternImage(id);
      expect(typeof img.width).toBe('number');
      expect(Number.isFinite(img.width)).toBe(true);
      expect(typeof img.height).toBe('number');
      expect(Number.isFinite(img.height)).toBe(true);
    }
  });

  it('data.length === width * height * 4 for every id', () => {
    for (const id of FILL_PATTERN_IDS) {
      const img = makeFillPatternImage(id);
      expect(img.data.length).toBe(img.width * img.height * 4);
    }
  });

  it('data is a Uint8ClampedArray for every id', () => {
    for (const id of FILL_PATTERN_IDS) {
      const img = makeFillPatternImage(id);
      expect(img.data).toBeInstanceOf(Uint8ClampedArray);
    }
  });

  it('each pattern generates a non-zero tile (at least one non-transparent pixel)', () => {
    for (const id of FILL_PATTERN_IDS) {
      const img = makeFillPatternImage(id);
      let hasAlpha = false;
      for (let i = 3; i < img.data.length; i += 4) {
        if (img.data[i] > 0) { hasAlpha = true; break; }
      }
      expect(hasAlpha).toBe(true);
    }
  });

  it('all patterns produce distinct pixel data', () => {
    const images = FILL_PATTERN_IDS.map((id) => makeFillPatternImage(id));
    for (let i = 0; i < images.length; i++) {
      for (let j = i + 1; j < images.length; j++) {
        const same = images[i].data.every((v, k) => v === images[j].data[k]);
        expect(same, `patterns[${i}] (${FILL_PATTERN_IDS[i]}) and patterns[${j}] (${FILL_PATTERN_IDS[j]}) are identical`).toBe(false);
      }
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('FILL_PATTERN_IMAGES', () => {
  it('lists one image per built-in pattern, drawn by makeFillPatternImage', () => {
    expect(FILL_PATTERN_IMAGES.map((image) => image.id)).toEqual([...FILL_PATTERN_IDS]);
    for (const image of FILL_PATTERN_IMAGES) {
      if (image.kind !== 'image') throw new Error(`${image.id} is not an image`);
      expect(image.data()).toEqual(makeFillPatternImage(image.id));
    }
  });

  it('registers no pattern as an SDF icon, since patterns are full-color tiles', () => {
    for (const image of FILL_PATTERN_IMAGES) {
      expect(image).not.toHaveProperty('options.sdf', true);
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('tintedFillPattern', () => {
  /** The first opaque pixel of a tile. */
  function firstOpaque(img: { data: Uint8ClampedArray }) {
    for (let i = 0; i < img.data.length; i += 4) {
      if (img.data[i + 3] === 255) return [img.data[i], img.data[i + 1], img.data[i + 2]];
    }
    return null;
  }

  it('names the tinted variant by its colour and draws the tile in it', () => {
    const tinted = tintedFillPattern('geolens-fill-hatch', '#1d4ed8');
    expect(tinted?.id).toBe('geolens-fill-hatch#1d4ed8');
    if (tinted?.kind !== 'image') throw new Error('no tinted image');
    expect(firstOpaque(tinted.data())).toEqual([29, 78, 216]);
  });

  it('paints the tint into the tile pixels', () => {
    const tinted = makeFillPatternImage('geolens-fill-hatch', [255, 0, 0]);
    const plain = makeFillPatternImage('geolens-fill-hatch');
    // First opaque pixel of each: red vs the legacy grey.
    expect(firstOpaque(tinted)).toEqual([255, 0, 0]);
    expect(firstOpaque(plain)).toEqual([80, 80, 80]);
  });

  it('normalises case so one tile serves #1D4ED8 and #1d4ed8', () => {
    expect(tintedFillPattern('geolens-fill-hatch', '#1D4ED8')?.id).toBe(tintedFillPattern('geolens-fill-hatch', '#1d4ed8')?.id);
  });

  it('expands 3-digit hex', () => {
    expect(tintedFillPattern('geolens-fill-hatch', '#f00')?.id).toBe('geolens-fill-hatch#ff0000');
  });

  it('stays plain with no tint, a colour that is not hex, or an id that is not built in', () => {
    expect(tintedFillPattern('geolens-fill-hatch', undefined)).toBeNull();
    // A data-driven expression stringifies to something that is not a colour.
    expect(tintedFillPattern('geolens-fill-hatch', 'rgb(1,2,3)')).toBeNull();
    expect(tintedFillPattern('some-sprite-id', '#ff0000')).toBeNull();
  });
});
