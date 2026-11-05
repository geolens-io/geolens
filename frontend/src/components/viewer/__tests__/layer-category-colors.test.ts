import { SAVED_LAYERS, toSharedLayer } from '@/test/fixtures/saved-layers';
import { layerCategoryColors } from '../layer-category-colors';

describe('layerCategoryColors', () => {
  it("gives each value of the style column the colour the layer's legend shows for it", () => {
    const colors = layerCategoryColors(toSharedLayer(SAVED_LAYERS.categorical))!;
    expect(colors.column).toBe('zone');
    expect(['R', 'C', 'I'].map((value) => colors.colorOf(value))).toEqual(['#66c2a5', '#fc8d62', '#8da0cb']);
  });

  it('keeps categories that share a legend label apart by value', () => {
    const base = SAVED_LAYERS.categorical;
    const layer = toSharedLayer({
      ...base,
      style_config: {
        ...base.style_config,
        categories: (base.style_config!.categories as { value: string; color: string }[]).map((entry) => ({
          ...entry,
          label: 'Zone',
        })),
      },
    });
    const colors = layerCategoryColors(layer)!;
    expect(['R', 'C', 'I'].map((value) => colors.colorOf(value))).toEqual(['#66c2a5', '#fc8d62', '#8da0cb']);
  });

  it('gives a value the style does not list the colour of its other class', () => {
    expect(layerCategoryColors(toSharedLayer(SAVED_LAYERS.categorical))!.colorOf('X')).toBe('#cccccc');
  });

  it('is null for a layer that is not coloured by categories', () => {
    expect(layerCategoryColors(toSharedLayer(SAVED_LAYERS.polygon))).toBeNull();
    expect(layerCategoryColors(toSharedLayer(SAVED_LAYERS.graduatedColor))).toBeNull();
  });

  it('is null once the paint no longer draws the stored categories', () => {
    const layer = toSharedLayer({ ...SAVED_LAYERS.categorical, paint: { 'fill-color': '#3b82f6' } });
    expect(layerCategoryColors(layer)).toBeNull();
  });
});
