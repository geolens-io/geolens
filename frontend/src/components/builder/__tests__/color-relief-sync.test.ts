// buildElevationExpression maps elevation to a named ramp's colours, transparent below the lowest land.
import { describe, it, expect } from 'vitest';
import { buildElevationExpression } from '../color-relief-sync';

// ---------------------------------------------------------------------------
// buildElevationExpression
// ---------------------------------------------------------------------------
describe('buildElevationExpression', () => {
  // fix(#455): 3 header tokens + 3 no-data guard pairs + 7 ramp pairs.
  const HEADER = 3;
  const GUARD_PAIRS = 3;
  const RAMP_START = HEADER + GUARD_PAIRS * 2;

  it('returns an interpolate expression starting with the correct tokens', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[0]).toBe('interpolate');
    expect(expr[1]).toEqual(['linear']);
    expect(expr[2]).toEqual(['elevation']);
  });

  it('produces the guard + 7 color stops (23 tokens total)', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr.length).toBe(HEADER + (GUARD_PAIRS + 7) * 2);
  });

  // fix(#455): no-data pixels read as the -10000 m encoding floor and used to
  // clamp to the first ramp color, painting a solid fringe beyond the DEM
  // footprint. The ramp must hold fully transparent through the guard band.
  it('holds transparent from the encoding floor to below the lowest land', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr.slice(HEADER, RAMP_START)).toEqual([
      -10000, 'rgba(0,0,0,0)',
      -500, 'rgba(0,0,0,0)',
      -499, expr[RAMP_START + 1],
    ]);
  });

  it('first ramp stop is at elevMin (default 0)', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[RAMP_START]).toBe(0);
  });

  it('last elevation stop is at elevMax (default 4000)', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[expr.length - 2]).toBe(4000);
  });

  it('elevation stops are evenly spaced across 0-4000 m', () => {
    const expr = buildElevationExpression('Viridis');
    const stops: number[] = [];
    for (let i = RAMP_START; i < expr.length; i += 2) {
      stops.push(expr[i] as number);
    }
    expect(stops).toHaveLength(7);
    const step = 4000 / 6;
    for (let i = 0; i < stops.length; i++) {
      expect(stops[i]).toBeCloseTo(i * step, 5);
    }
  });

  it('ramp color values are hex strings', () => {
    const expr = buildElevationExpression('Viridis');
    for (let i = RAMP_START + 1; i < expr.length; i += 2) {
      expect(typeof expr[i]).toBe('string');
      expect((expr[i] as string).startsWith('#')).toBe(true);
    }
  });

  it('respects custom elevMin and elevMax', () => {
    const expr = buildElevationExpression('Inferno', 500, 2000);
    expect(expr[RAMP_START]).toBe(500);
    expect(expr[expr.length - 2]).toBe(2000);
  });

  // fix(#455): an elevMin inside the guard band (e.g. bathymetry) must skip
  // the guard rather than emit non-ascending interpolate stops.
  it('skips the guard when elevMin dips into the guard band', () => {
    const expr = buildElevationExpression('Viridis', -600, 4000);
    expect(expr.length).toBe(HEADER + 7 * 2);
    expect(expr[HEADER]).toBe(-600);
  });

  it('falls back to a valid expression for an unknown ramp name', () => {
    // getRampColors falls back to YlOrRd for unknown names (Threat T-1140-05)
    const expr = buildElevationExpression('NotARealRamp');
    expect(expr[0]).toBe('interpolate');
    expect(expr.length).toBe(HEADER + (GUARD_PAIRS + 7) * 2);
  });

  // test(#828): render side of hypso_reversed — the flag regressed once in the
  // 1.6.0 cycle. reversed=true must actually flip the 7 ramp colors.
  it('reversed=true reverses the ramp colors relative to reversed=false', () => {
    const forward = buildElevationExpression('Viridis', undefined, undefined, false);
    const reversed = buildElevationExpression('Viridis', undefined, undefined, true);

    const colorsOf = (expr: unknown[]) => {
      const colors: unknown[] = [];
      for (let i = RAMP_START + 1; i < expr.length; i += 2) colors.push(expr[i]);
      return colors;
    };
    const forwardColors = colorsOf(forward as unknown[]);
    expect(colorsOf(reversed as unknown[])).toEqual([...forwardColors].reverse());
    // Sanity: Viridis is not palindromic, so the expressions must differ.
    expect(reversed).not.toEqual(forward);
    // Elevation stops are unchanged — only the colors flip.
    for (let i = RAMP_START; i < (forward as unknown[]).length; i += 2) {
      expect((reversed as unknown[])[i]).toBe((forward as unknown[])[i]);
    }
  });

  it('omitting the reversed flag defaults to the non-reversed ramp', () => {
    expect(buildElevationExpression('Viridis')).toEqual(
      buildElevationExpression('Viridis', undefined, undefined, false),
    );
  });
});
