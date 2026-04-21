import type { TFunction } from 'i18next';
import type { MapLayerResponse } from '@/types/api';

/**
 * Generate geometry-aware suggestions for the chat empty state.
 * Simple fixed suggestions per geometry type — no column introspection.
 */

function mentionName(layer: MapLayerResponse): string {
  const name = layer.display_name ?? layer.dataset_name;
  return name.includes(' ') ? `@[${name}]` : `@${name}`;
}

// Accept a TFunction bound to any namespace; the caller provides its own
// scoped instance (e.g. from useTranslation('builder')).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyTFunction = TFunction<any, undefined>;

export function getSmartSuggestions(layers: MapLayerResponse[], t: AnyTFunction): string[] {
  const suggestions: string[] = [];

  for (const layer of layers) {
    if (suggestions.length >= 4) break;

    const mention = mentionName(layer);
    const geom = (layer.dataset_geometry_type ?? '').toLowerCase();

    if (geom.includes('point')) {
      if (suggestions.length < 4)
        suggestions.push(t('chat.suggestions.colorByAttribute', { name: mention }));
    } else if (geom.includes('polygon') || geom.includes('multipolygon')) {
      if (!layer.style_config && suggestions.length < 4)
        suggestions.push(t('chat.suggestions.colorByAttribute', { name: mention }));
      if (suggestions.length < 4)
        suggestions.push(t('chat.suggestions.areaLabels', { name: mention }));
    } else if (geom.includes('line')) {
      if (suggestions.length < 4)
        suggestions.push(t('chat.suggestions.colorByAttribute', { name: mention }));
    } else if (layer.layer_type === 'raster' || geom === '') {
      if (suggestions.length < 4)
        suggestions.push(t('chat.suggestions.adjustOpacity', { name: mention }));
    }
  }

  if (suggestions.length < 4) {
    suggestions.push(t('chat.suggestions.addDataset'));
  }

  return suggestions.slice(0, 4);
}
