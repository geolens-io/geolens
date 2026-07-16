import { describe, it, expect } from 'vitest';
import {
  buildCategoricalExpression,
  buildGraduatedSizeExpression,
  getSizeProperty,
  getColorProperty,
  reverseRamp,
  cvdSafeRamps,
  getRampColors,
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
  nextRotatingRamp,
  suggestRampForMode,
} from '../color-ramps';

describe('buildGraduatedSizeExpression', () => {
  it('returns a step expression with correct shape', () => {
    const result = buildGraduatedSizeExpression('pop', [100, 500, 1000], [3, 6, 10, 16]);
    expect(result).toEqual(['case', ['==', ['get', 'pop'], null], 0, ['step', ['get', 'pop'], 3, 100, 6, 500, 10, 1000, 16]]);
  });

  it('throws if sizes.length !== breaks.length + 1', () => {
    expect(() => buildGraduatedSizeExpression('pop', [100, 500], [3, 6])).toThrow();
    expect(() => buildGraduatedSizeExpression('pop', [100], [3, 6, 10])).toThrow();
  });

  it('handles single break (2 classes)', () => {
    const result = buildGraduatedSizeExpression('x', [50], [4, 12]);
    expect(result).toEqual(['case', ['==', ['get', 'x'], null], 0, ['step', ['get', 'x'], 4, 50, 12]]);
  });
});

describe('getSizeProperty', () => {
  it('returns circle-radius for Point + radius', () => {
    expect(getSizeProperty('Point', 'radius')).toBe('circle-radius');
  });

  it('returns circle-radius for MultiPoint + radius', () => {
    expect(getSizeProperty('MultiPoint', 'radius')).toBe('circle-radius');
  });

  it('returns line-width for LineString + width', () => {
    expect(getSizeProperty('LineString', 'width')).toBe('line-width');
  });

  it('returns line-width for MultiLineString + width', () => {
    expect(getSizeProperty('MultiLineString', 'width')).toBe('line-width');
  });

  it('returns null for Polygon + radius (no size property for polygons)', () => {
    expect(getSizeProperty('Polygon', 'radius')).toBeNull();
  });

  it('returns null for Point + color (color is not a size target)', () => {
    expect(getSizeProperty('Point', 'color')).toBeNull();
  });

  it('returns null for null geometryType', () => {
    expect(getSizeProperty(null, 'radius')).toBeNull();
  });

  it('returns null for MultiPolygon + width', () => {
    expect(getSizeProperty('MultiPolygon', 'width')).toBeNull();
  });

  it('returns null for LineString + radius (wrong target for line)', () => {
    expect(getSizeProperty('LineString', 'radius')).toBeNull();
  });

  it('returns null for Point + width (wrong target for point)', () => {
    expect(getSizeProperty('Point', 'width')).toBeNull();
  });
});

describe('reverseRamp', () => {
  it('reverses a 3-color array', () => {
    expect(reverseRamp(['#000', '#888', '#fff'])).toEqual(['#fff', '#888', '#000']);
  });

  it('reversing twice is identity', () => {
    const colors = ['#000', '#888', '#fff'];
    expect(reverseRamp(reverseRamp(colors))).toEqual(colors);
  });

  it('does not mutate the input array', () => {
    const colors = ['#aaa', '#bbb', '#ccc'];
    reverseRamp(colors);
    expect(colors).toEqual(['#aaa', '#bbb', '#ccc']);
  });

  it('handles a single color (round-trips)', () => {
    expect(reverseRamp(['#ff0000'])).toEqual(['#ff0000']);
  });
});

describe('getRampColors with reversed flag', () => {
  it('reversed=true returns the reverse of reversed=false for same ramp + count', () => {
    const forward = getRampColors('Blues', 5, false);
    const backward = getRampColors('Blues', 5, true);
    expect(backward).toEqual(reverseRamp(forward));
  });

  it('reversed=false (default) equals calling without the flag', () => {
    expect(getRampColors('Viridis', 7, false)).toEqual(getRampColors('Viridis', 7));
  });

  it('reversed flag round-trip: reversed(reversed) equals original', () => {
    const colors = getRampColors('YlOrRd', 5);
    const reversed = reverseRamp(colors);
    expect(reverseRamp(reversed)).toEqual(colors);
  });
});

describe('cvdSafeRamps', () => {
  it('excludes Spectral (cvdSafe: false) from diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    expect(safe.map((r) => r.name)).not.toContain('Spectral');
  });

  it('excludes RdYlGn (cvdSafe: false) from diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    expect(safe.map((r) => r.name)).not.toContain('RdYlGn');
  });

  it('includes Viridis (cvdSafe: true) in sequential ramps', () => {
    const safe = cvdSafeRamps(SEQUENTIAL_RAMPS);
    expect(safe.map((r) => r.name)).toContain('Viridis');
  });

  it('includes RdBu and BrBG (cvdSafe: true) in diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).toContain('RdBu');
    expect(names).toContain('BrBG');
  });

  it('excludes Set1, Set3, Accent, Pastel1, Pastel2 from qualitative ramps', () => {
    const safe = cvdSafeRamps(QUALITATIVE_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).not.toContain('Set1');
    expect(names).not.toContain('Set3');
    expect(names).not.toContain('Accent');
    expect(names).not.toContain('Pastel1');
    expect(names).not.toContain('Pastel2');
  });

  it('includes Set2, Dark2, Paired in qualitative ramps', () => {
    const safe = cvdSafeRamps(QUALITATIVE_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).toContain('Set2');
    expect(names).toContain('Dark2');
    expect(names).toContain('Paired');
  });

  it('all sequential ramps are cvdSafe', () => {
    expect(cvdSafeRamps(SEQUENTIAL_RAMPS)).toHaveLength(SEQUENTIAL_RAMPS.length);
  });
});

describe('getColorProperty regression', () => {
  it('returns fill-color for Polygon', () => {
    expect(getColorProperty('Polygon')).toBe('fill-color');
  });

  it('returns line-color for LineString', () => {
    expect(getColorProperty('LineString')).toBe('line-color');
  });

  it('returns circle-color for Point', () => {
    expect(getColorProperty('Point')).toBe('circle-color');
  });

  it('returns fill-color for null', () => {
    expect(getColorProperty(null)).toBe('fill-color');
  });

  it('returns circle-color for MultiPoint', () => {
    expect(getColorProperty('MultiPoint')).toBe('circle-color');
  });
});

// ---------------------------------------------------------------------------
// ENH-08: nextRotatingRamp + suggestRampForMode
// ---------------------------------------------------------------------------

describe('nextRotatingRamp — graduated (sequential ramps)', () => {
  it('index 0 returns the first sequential ramp (YlOrRd)', () => {
    expect(nextRotatingRamp('graduated', 0)).toBe('YlOrRd');
  });

  it('produces N distinct ramp names before cycling (no early collision)', () => {
    // Collect one full rotation cycle; all names must be distinct.
    const ROTATION_LEN = 14; // matches GRADUATED_ROTATION.length
    const names = Array.from({ length: ROTATION_LEN }, (_, i) =>
      nextRotatingRamp('graduated', i),
    );
    const unique = new Set(names);
    expect(unique.size).toBe(ROTATION_LEN);
  });

  it('cycles: nextRotatingRamp(graduated, k) === nextRotatingRamp(graduated, k + ROTATION_LEN)', () => {
    const ROTATION_LEN = 14;
    for (let k = 0; k < ROTATION_LEN; k++) {
      expect(nextRotatingRamp('graduated', k)).toBe(
        nextRotatingRamp('graduated', k + ROTATION_LEN),
      );
    }
  });

  it('returns a sequential ramp name (one of SEQUENTIAL_RAMPS)', () => {
    const seqNames = SEQUENTIAL_RAMPS.map((r) => r.name) as string[];
    for (let i = 0; i < 14; i++) {
      expect(seqNames).toContain(nextRotatingRamp('graduated', i));
    }
  });

  it('first entry is CVD-safe', () => {
    const name = nextRotatingRamp('graduated', 0);
    const ramp = SEQUENTIAL_RAMPS.find((r) => r.name === name);
    expect(ramp?.cvdSafe).toBe(true);
  });
});

describe('nextRotatingRamp — categorical (qualitative ramps)', () => {
  it('index 0 returns the first qualitative ramp (Set2)', () => {
    expect(nextRotatingRamp('categorical', 0)).toBe('Set2');
  });

  it('produces N distinct ramp names before cycling (no early collision)', () => {
    const ROTATION_LEN = 6; // matches CATEGORICAL_ROTATION.length
    const names = Array.from({ length: ROTATION_LEN }, (_, i) =>
      nextRotatingRamp('categorical', i),
    );
    const unique = new Set(names);
    expect(unique.size).toBe(ROTATION_LEN);
  });

  it('cycles: nextRotatingRamp(categorical, k) === nextRotatingRamp(categorical, k + ROTATION_LEN)', () => {
    const ROTATION_LEN = 6;
    for (let k = 0; k < ROTATION_LEN; k++) {
      expect(nextRotatingRamp('categorical', k)).toBe(
        nextRotatingRamp('categorical', k + ROTATION_LEN),
      );
    }
  });

  it('first three entries are CVD-safe qualitative ramps', () => {
    const cvdSafe = cvdSafeRamps(QUALITATIVE_RAMPS).map((r) => r.name) as string[];
    expect(cvdSafe).toContain(nextRotatingRamp('categorical', 0));
    expect(cvdSafe).toContain(nextRotatingRamp('categorical', 1));
    expect(cvdSafe).toContain(nextRotatingRamp('categorical', 2));
  });
});

describe('suggestRampForMode', () => {
  it('returns a sequential ramp for graduated mode', () => {
    const name = suggestRampForMode('graduated');
    const seqNames = SEQUENTIAL_RAMPS.map((r) => r.name) as string[];
    expect(seqNames).toContain(name);
  });

  it('returns a qualitative ramp for categorical mode', () => {
    const name = suggestRampForMode('categorical');
    const qualNames = QUALITATIVE_RAMPS.map((r) => r.name) as string[];
    expect(qualNames).toContain(name);
  });

  it('graduated suggestion is CVD-safe', () => {
    const name = suggestRampForMode('graduated');
    const ramp = SEQUENTIAL_RAMPS.find((r) => r.name === name);
    expect(ramp?.cvdSafe).toBe(true);
  });

  it('categorical suggestion is CVD-safe', () => {
    const name = suggestRampForMode('categorical');
    const ramp = QUALITATIVE_RAMPS.find((r) => r.name === name);
    expect(ramp?.cvdSafe).toBe(true);
  });

  it('graduated default is nextRotatingRamp(graduated, 0)', () => {
    expect(suggestRampForMode('graduated')).toBe(nextRotatingRamp('graduated', 0));
  });

  it('categorical default is nextRotatingRamp(categorical, 0)', () => {
    expect(suggestRampForMode('categorical')).toBe(nextRotatingRamp('categorical', 0));
  });
});

// ---------------------------------------------------------------------------
// fix(#527 B-054/S-03): empty categorical map emits the bare fallback, never a
// zero-pair ['match'] (below spec minimum arity — addLayer throws, swallowed,
// and the layer silently never renders).
// ---------------------------------------------------------------------------
describe('buildCategoricalExpression empty-map guard (B-054/S-03)', () => {
  it('returns the bare fallback color when valueColorMap is empty', () => {
    expect(buildCategoricalExpression('kind', [], '#aabbcc')).toBe('#aabbcc');
  });

  it('still emits the null-safe match expression when pairs exist', () => {
    expect(buildCategoricalExpression('kind', [['a', '#111111']], '#aabbcc')).toEqual([
      'case',
      ['==', ['get', 'kind'], null],
      '#aabbcc',
      ['match', ['get', 'kind'], 'a', '#111111', '#aabbcc'],
    ]);
  });
});
