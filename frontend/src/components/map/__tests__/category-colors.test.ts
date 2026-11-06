import { SAVED_LAYERS, toSharedLayer } from '@/test/fixtures/saved-layers';
import { categoryColors } from '../legend-facts';

const zones = toSharedLayer(SAVED_LAYERS.categorical);

describe('categoryColors', () => {
  it('gives each value of the painted column the colour the map draws for it', () => {
    const colors = categoryColors(zones)!;
    expect(colors.column).toBe('zone');
    expect(['R', 'C', 'I'].map((value) => colors.colorOf(value))).toEqual(['#66c2a5', '#fc8d62', '#8da0cb']);
  });

  it('gives a value the paint does not list the fallback colour, as the map does', () => {
    expect(categoryColors(zones)!.colorOf('X')).toBe('#cccccc');
    expect(categoryColors(zones)!.colorOf(null)).toBe('#cccccc');
  });

  it('follows the paint where the stored categories disagree with it', () => {
    const layer = toSharedLayer({
      ...SAVED_LAYERS.categorical,
      paint: { 'fill-color': ['match', ['get', 'zone'], ['school', 'clinic'], '#ff00ff', '#cccccc'] },
      style_config: {
        mode: 'categorical',
        column: 'zone',
        categories: [
          { value: 'school', color: '#ff00ff' },
          { value: 'clinic', color: '#0000ff' },
        ],
      },
    });
    expect(['school', 'clinic'].map((value) => categoryColors(layer)!.colorOf(value))).toEqual(['#ff00ff', '#ff00ff']);
  });

  it('is null for a layer that is not coloured by a column match', () => {
    expect(categoryColors(toSharedLayer(SAVED_LAYERS.polygon))).toBeNull();
    expect(categoryColors(toSharedLayer(SAVED_LAYERS.graduatedColor))).toBeNull();
    expect(categoryColors(toSharedLayer({ ...SAVED_LAYERS.categorical, paint: { 'fill-color': '#3b82f6' } }))).toBeNull();
  });

  const numeric = (colorExpression: unknown) =>
    toSharedLayer({ ...SAVED_LAYERS.categorical, paint: { 'fill-color': colorExpression } });

  it('draws a null with the fallback where a null guard would otherwise read it as 0', () => {
    const layer = numeric([
      'case',
      ['==', ['get', 'n'], null],
      '#cccccc',
      ['match', ['to-number', ['get', 'n'], 0], [0], '#ff0000', [1], '#00ff00', '#cccccc'],
    ]);
    const colors = categoryColors(layer)!;
    expect(colors.colorOf(0)).toBe('#ff0000');
    expect(colors.colorOf(null)).toBe('#cccccc');
  });

  it('leaves a value without a bar colour when its arm is transparent', () => {
    const layer = numeric(['match', ['get', 'zone'], ['A'], 'rgba(0,0,0,0)', ['B'], '#00ff00', '#cccccc']);
    const colors = categoryColors(layer)!;
    expect(colors.colorOf('A')).toBeUndefined();
    expect(colors.colorOf('B')).toBe('#00ff00');
  });
});
