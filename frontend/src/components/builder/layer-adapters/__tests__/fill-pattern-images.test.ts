import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  FILL_PATTERN_IDS,
  makeFillPatternImage,
  ensureFillPatternImages,
  ensureTintedFillPatternImage,
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
describe('ensureFillPatternImages', () => {
  let mockMap: {
    hasImage: ReturnType<typeof vi.fn>;
    addImage: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockMap = {
      hasImage: vi.fn(() => false),
      addImage: vi.fn(),
    };
  });

  it('calls addImage once per id when hasImage returns false', () => {
    ensureFillPatternImages(mockMap as unknown as import('maplibre-gl').Map);
    expect(mockMap.addImage).toHaveBeenCalledTimes(FILL_PATTERN_IDS.length);
    for (const id of FILL_PATTERN_IDS) {
      expect(mockMap.addImage).toHaveBeenCalledWith(id, expect.objectContaining({
        width: expect.any(Number),
        height: expect.any(Number),
        data: expect.any(Uint8ClampedArray),
      }));
    }
  });

  it('does NOT call addImage when hasImage returns true (idempotency)', () => {
    mockMap.hasImage = vi.fn(() => true);
    ensureFillPatternImages(mockMap as unknown as import('maplibre-gl').Map);
    expect(mockMap.addImage).toHaveBeenCalledTimes(0);
  });

  it('does not throw if addImage throws (swallows errors)', () => {
    mockMap.addImage = vi.fn(() => { throw new Error('map not ready'); });
    expect(() => ensureFillPatternImages(mockMap as unknown as import('maplibre-gl').Map)).not.toThrow();
  });

  it('is NOT registered with sdf:true (patterns are full-color tiles)', () => {
    ensureFillPatternImages(mockMap as unknown as import('maplibre-gl').Map);
    for (const call of mockMap.addImage.mock.calls) {
      // Third argument should be absent or not have sdf:true
      const options = call[2] as Record<string, unknown> | undefined;
      if (options) {
        expect(options.sdf).not.toBe(true);
      }
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// fix(#914): tinted variants. The generators used to hardcode rgb(80,80,80), so a
// pattern never followed the layer's fill colour and read as "my fill disappeared"
// on a light basemap.
describe('ensureTintedFillPatternImage', () => {
  function makeMap(existing: string[] = []) {
    const have = new Set(existing);
    return {
      hasImage: vi.fn((id: string) => have.has(id)),
      addImage: vi.fn((id: string) => have.add(id)),
    };
  }

  it('registers a tinted variant under a colour-namespaced id and returns it', () => {
    const map = makeMap();
    const id = ensureTintedFillPatternImage(
      map as never, 'geolens-fill-hatch', '#1d4ed8',
    );
    expect(id).toBe('geolens-fill-hatch#1d4ed8');
    expect(map.addImage).toHaveBeenCalledWith('geolens-fill-hatch#1d4ed8', expect.anything());
  });

  it('paints the tint into the tile pixels', () => {
    const tinted = makeFillPatternImage('geolens-fill-hatch', [255, 0, 0]);
    const plain = makeFillPatternImage('geolens-fill-hatch');
    // First opaque pixel of each: red vs the legacy grey.
    const firstOpaque = (img: { data: Uint8ClampedArray }) => {
      for (let i = 0; i < img.data.length; i += 4) {
        if (img.data[i + 3] === 255) return [img.data[i], img.data[i + 1], img.data[i + 2]];
      }
      return null;
    };
    expect(firstOpaque(tinted)).toEqual([255, 0, 0]);
    expect(firstOpaque(plain)).toEqual([80, 80, 80]);
  });

  it('is idempotent — an already-registered tint is not re-added', () => {
    const map = makeMap(['geolens-fill-hatch#1d4ed8']);
    ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', '#1d4ed8');
    expect(map.addImage).not.toHaveBeenCalled();
  });

  it('normalises case so one tile serves #1D4ED8 and #1d4ed8', () => {
    const map = makeMap();
    const upper = ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', '#1D4ED8');
    const lower = ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', '#1d4ed8');
    expect(upper).toBe(lower);
    expect(map.addImage).toHaveBeenCalledTimes(1);
  });

  it('expands 3-digit hex', () => {
    const map = makeMap();
    expect(ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', '#f00'))
      .toBe('geolens-fill-hatch#ff0000');
  });

  it('falls back to the plain id when there is no tint, when the colour is not hex, and for unknown ids', () => {
    const map = makeMap();
    expect(ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', undefined))
      .toBe('geolens-fill-hatch');
    // A data-driven expression stringifies to something that is not a colour.
    expect(ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', 'rgb(1,2,3)'))
      .toBe('geolens-fill-hatch');
    expect(ensureTintedFillPatternImage(map as never, 'some-sprite-id', '#ff0000'))
      .toBe('some-sprite-id');
    expect(map.addImage).not.toHaveBeenCalled();
  });

  it('returns the plain id when addImage throws', () => {
    const map = {
      hasImage: vi.fn(() => false),
      addImage: vi.fn(() => { throw new Error('style not loaded'); }),
    };
    expect(ensureTintedFillPatternImage(map as never, 'geolens-fill-hatch', '#ff0000'))
      .toBe('geolens-fill-hatch');
  });
});
