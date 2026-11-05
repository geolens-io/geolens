import { legendFacts } from '@/components/map/legend-facts';
import type { LayerCategoryColors } from '@/components/widgets/layer-colors';

type LegendLayer = Parameters<typeof legendFacts>[0];

/**
 * The colour the layer's map style gives each value of its category column,
 * read from the legend's own classes so a chart and the map read as one key.
 * Null when the layer isn't coloured by categories. A value the style lists
 * takes its class colour; one it doesn't takes the "other" class colour, if the
 * legend names one.
 */
export function layerCategoryColors(layer: LegendLayer): LayerCategoryColors | null {
  const config = layer.style_config;
  const classes = legendFacts(layer)?.classes?.find((entry) => entry.mode === 'categorical' && entry.target === 'color');
  if (config?.mode !== 'categorical' || !config.column || !classes) return null;
  const stored = config.categories ?? [];
  const labelOf = (category: (typeof stored)[number]) => category.label ?? String(category.value);
  // The stored categories belong to the style column; the paint has to be drawing them.
  if (!stored.some((category) => classes.items.some((item) => item.label === labelOf(category)))) return null;
  const other = classes.items.find((item) => item.other)?.color;
  return {
    column: config.column,
    colorOf: (key) => {
      const category = stored.find((entry) =>
        key === null || entry.value === null ? key === entry.value : String(entry.value) === String(key),
      );
      if (!category) return other;
      return classes.items.find((item) => item.label === labelOf(category))?.color ?? category.color;
    },
  };
}
