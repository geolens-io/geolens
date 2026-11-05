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
});
