import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FILL_PATTERN_IDS, makeFillPatternImage, ensureFillPatternImages } from '../fill-pattern-images';

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
