import { describe, expect, it } from 'vitest';
import { buildGraduatedExpression, colorClassificationIsOrphaned } from '@/lib/color-ramps';
import { savedLayer } from '@/test/fixtures/saved-layers';
import { legendFacts } from '../legend-facts';

// What the ArcGIS web map translator saves for a classBreaks renderer.
const COLORS = ['#00ff00', '#ffff00', '#ff0000'];
const BREAKS = [10, 100];
const PAINT = {
  'fill-color': [
    'case',
    ['==', ['get', 'POP'], null],
    '#cccccc',
    ['step', ['get', 'POP'], '#00ff00', 10, '#ffff00', 100, '#ff0000'],
  ],
  'fill-opacity': 1,
};
const STYLE_CONFIG = {
  mode: 'graduated' as const,
  column: 'POP',
  method: 'manual' as const,
  classCount: 3,
  breaks: BREAKS,
  colors: COLORS,
};

describe('an imported ArcGIS class-breaks layer', () => {
  it('is a graduated classification the builder backs with its paint', () => {
    expect(colorClassificationIsOrphaned(STYLE_CONFIG, PAINT, 'MULTIPOLYGON')).toBe(false);
  });

  it('lists its classes in the legend', () => {
    const classes = legendFacts(savedLayer({ paint: PAINT, style_config: STYLE_CONFIG }))?.classes;
    expect(classes).toMatchObject([{ mode: 'graduated', target: 'color', breaks: BREAKS }]);
    expect(classes?.[0].items.map((item) => item.color)).toEqual(COLORS);
  });

  it('is the expression the builder writes, so a colour edit keeps the same shape', () => {
    expect(PAINT['fill-color']).toEqual(buildGraduatedExpression('POP', BREAKS, COLORS));
  });
});
