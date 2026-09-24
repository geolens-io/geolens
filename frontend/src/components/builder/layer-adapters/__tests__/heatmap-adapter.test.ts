// buildHeatmapColorExpression maps heatmap density onto a named ramp, reversed on request.
import { describe, it, expect } from 'vitest';
import { buildHeatmapColorExpression } from '../heatmap-adapter';

describe('buildHeatmapColorExpression', () => {
  // Density-stop color positions in the buildHeatmapColorExpression output:
  // ['interpolate', ['linear'], ['heatmap-density'], 0, transparent, 0.2, c0, ...]
  const COLOR_INDICES = [6, 8, 10, 12, 14];
  const extractColors = (expr: unknown[]) => COLOR_INDICES.map((i) => expr[i]);

  it('reverses the color stops of the forward ramp', () => {
    const forward = buildHeatmapColorExpression('YlOrRd', false);
    const reversed = buildHeatmapColorExpression('YlOrRd', true);
    const forwardColors = extractColors(forward);
    expect(extractColors(reversed)).toEqual([...forwardColors].reverse());
    // Sanity: the ramp is not palindromic, so the two must actually differ.
    expect(reversed).not.toEqual(forward);
    // Density 0 stays transparent in both directions.
    expect(reversed[4]).toBe(forward[4]);
  });

  it('defaults to reversed=false when the flag is omitted', () => {
    expect(buildHeatmapColorExpression('YlOrRd')).toEqual(
      buildHeatmapColorExpression('YlOrRd', false),
    );
  });
});
