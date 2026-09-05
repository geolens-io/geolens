import { describe, it, expect } from 'vitest';
import type { StyleConfig } from '@/types/api';
import {
  colorClassificationIsOrphaned,
  reconcileColorClassification,
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

// fix(#1856): qualitative palettes are discrete categories, not a gradient —
// sampling them continuously blended unrelated hues and washed small counts
// out toward grey. getRampColors now assigns palette entries directly.
describe('getRampColors on qualitative ramps (#1856)', () => {
  it('five categories on Set2 yield five distinct palette members', () => {
    const colors = getRampColors('Set2', 5);
    expect(new Set(colors).size).toBe(5);
    expect(colors).toEqual(getRampColors('Set2', 8).slice(0, 5));
  });

  it('cycles past the palette length instead of repeating the last color', () => {
    const eight = getRampColors('Set2', 8);
    const ten = getRampColors('Set2', 10);
    expect(ten.slice(0, 8)).toEqual(eight);
    expect(ten[8]).toBe(eight[0]);
    expect(ten[9]).toBe(eight[1]);
  });

  it('still resolves case-insensitively for a qualitative name', () => {
    expect(getRampColors('set2', 5)).toEqual(getRampColors('Set2', 5));
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

// fix(#910, codex P2): the one predicate both halves of the reconciliation read — the
// commit boundary in use-layer-map-sync.ts, and DataDrivenStyleEditor's skip guard.
describe('colorClassificationIsOrphaned', () => {
  const RAMP = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];
  const categorical = (extra: Record<string, unknown> = {}) =>
    ({
      mode: 'categorical',
      column: 'era',
      categories: [{ value: 'pre-war', color: '#ff0000' }],
      ...extra,
    }) as StyleConfig;

  it('is orphaned when the config claims classes the paint does not express', () => {
    expect(colorClassificationIsOrphaned(categorical(), { 'fill-color': '#3b82f6' }, 'Polygon')).toBe(true);
    expect(colorClassificationIsOrphaned(categorical(), {}, 'Polygon')).toBe(true);
  });

  it('is not orphaned while the expression is there', () => {
    expect(colorClassificationIsOrphaned(categorical(), { 'fill-color': RAMP }, 'Polygon')).toBe(false);
  });

  // fix(#461): an all-null column legitimately yields `categories: []`, and
  // buildCategoricalExpression emits a BARE colour for it rather than a below-arity
  // `match`. Calling that orphaned makes the editor regenerate on every render.
  it('is not orphaned by a config that claims no classes', () => {
    expect(colorClassificationIsOrphaned(categorical({ categories: [] }), { 'fill-color': '#3b82f6' }, 'Polygon')).toBe(false);
    expect(colorClassificationIsOrphaned({ mode: 'graduated', column: 'h' } as StyleConfig, {}, 'Polygon')).toBe(false);
  });

  // heatmap and symbol park a classification while the renderer paints something else
  // entirely — the same exemption hasUnsupportedBuilderState makes.
  it.each(['heatmap', 'symbol'])('is not orphaned under render_mode %s', (render_mode) => {
    expect(colorClassificationIsOrphaned(categorical({ render_mode }), {}, 'MultiPoint')).toBe(false);
  });

  // fix(#910, codex P2): an array alone is not proof. Advanced JSON or the AI can swap a
  // categorical `era` expression for one reading `status`, and the legend then reports
  // `era` over a map drawn by `status`.
  it('is orphaned when the expression classifies a different column', () => {
    const byStatus = ['match', ['get', 'status'], 'open', '#ff0000', '#00ff00'];
    expect(colorClassificationIsOrphaned(categorical(), { 'fill-color': byStatus }, 'Polygon')).toBe(true);
  });

  // The column can sit anywhere inside the expression — a builder classification is
  // wrapped in a `case` null-guard, and a hand-authored one can nest arbitrarily.
  it('finds the column at any depth, and accepts a multi-column expression that reads it', () => {
    const nested = ['case', ['==', ['get', 'era'], null], '#ccc', RAMP];
    expect(colorClassificationIsOrphaned(categorical(), { 'fill-color': nested }, 'Polygon')).toBe(false);
    // Reads `zone` as well as `era`. Guessing which `get` is "the" classification is
    // exactly what this must not do — a wrong guess deletes hand-authored categories.
    const multi = ['case', ['has', 'zone'], RAMP, '#ccc'];
    expect(colorClassificationIsOrphaned(categorical(), { 'fill-color': multi }, 'Polygon')).toBe(false);
  });

  // Without a column there is nothing to compare against, so the array is all we have.
  it('accepts any expression when the config names no column', () => {
    const byStatus = ['match', ['get', 'status'], 'open', '#ff0000', '#00ff00'];
    const noColumn = categorical({ column: undefined });
    expect(colorClassificationIsOrphaned(noColumn, { 'fill-color': byStatus }, 'Polygon')).toBe(false);
  });

  it('reads the colour key the geometry uses, not fill-color everywhere', () => {
    expect(colorClassificationIsOrphaned(categorical(), { 'circle-color': RAMP }, 'MultiPoint')).toBe(false);
    expect(colorClassificationIsOrphaned(categorical(), { 'line-color': RAMP }, 'MultiLineString')).toBe(false);
    // The same paint under a polygon geometry claims nothing about fill-color.
    expect(colorClassificationIsOrphaned(categorical(), { 'circle-color': RAMP }, 'Polygon')).toBe(true);
  });

  it('ignores a size target and a config that is not data-driven at all', () => {
    const sizeTarget = categorical({ mode: 'graduated', target: 'radius', colors: ['#111', '#222'] });
    expect(colorClassificationIsOrphaned(sizeTarget, {}, 'MultiPoint')).toBe(false);
    expect(colorClassificationIsOrphaned({ builder: { outlineWidth: 2 } } as StyleConfig, {}, 'Polygon')).toBe(false);
    expect(colorClassificationIsOrphaned(null, {}, 'Polygon')).toBe(false);
  });
});

describe('reconcileColorClassification', () => {
  const orphaned = {
    mode: 'categorical',
    column: 'era',
    ramp: 'Set2',
    categories: [{ value: 'pre-war', color: '#ff0000' }],
    colors: ['#ff0000'],
    breaks: [10],
    render_mode: 'cluster',
    builder: { outlineWidth: 3 },
  } as StyleConfig;

  it('drops the claim and keeps everything that is not the claim', () => {
    const next = reconcileColorClassification(orphaned, { 'fill-color': '#3b82f6' }, 'Polygon');
    expect(next?.mode).toBeUndefined();
    expect(next?.categories).toBeUndefined();
    expect(next?.colors).toBeUndefined();
    expect(next?.breaks).toBeUndefined();
    // fix(#910, codex P2): column and ramp too — a config carrying a column and no mode
    // reads to a freshly mounted DataDrivenStyleEditor as a live categorical
    // classification, which re-applied it over the paint that retired it.
    expect(next?.column).toBeUndefined();
    expect(next?.ramp).toBeUndefined();
    // Not the claim: the renderer and the builder block are untouched.
    expect(next?.render_mode).toBe('cluster');
    expect(next?.builder?.outlineWidth).toBe(3);
  });

  it('returns the config untouched (same reference) when nothing is orphaned', () => {
    const paint = { 'fill-color': ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'] };
    expect(reconcileColorClassification(orphaned, paint, 'Polygon')).toBe(orphaned);
  });

  it('collapses to null when the claim was all the config had', () => {
    const claimOnly = { mode: 'categorical', categories: [{ value: 'a', color: '#111' }] } as StyleConfig;
    expect(reconcileColorClassification(claimOnly, {}, 'Polygon')).toBeNull();
  });
});
