import type { MapLayerResponse } from '@/types/api';

/**
 * Generate geometry-aware suggestions for the chat empty state.
 * Simple fixed suggestions per geometry type — no column introspection.
 */

function mentionName(layer: MapLayerResponse): string {
  const name = layer.display_name ?? layer.dataset_name;
  return name.includes(' ') ? `@[${name}]` : `@${name}`;
}

type AnyTFunction = (key: string, options?: Record<string, unknown>) => string;

export function getSmartSuggestions(layers: MapLayerResponse[], t: AnyTFunction): string[] {
  const suggestions: string[] = [];
  const pushSuggestion = (suggestion: string) => {
    if (suggestions.length < 4 && !suggestions.includes(suggestion)) {
      suggestions.push(suggestion);
    }
  };

  for (const layer of layers) {
    if (suggestions.length >= 4) break;

    const mention = mentionName(layer);
    const geom = (layer.dataset_geometry_type ?? '').toLowerCase();

    if (geom.includes('point')) {
      pushSuggestion(t('chat.suggestions.colorByAttribute', { name: mention }));
    } else if (geom.includes('polygon') || geom.includes('multipolygon')) {
      if (!layer.style_config) {
        pushSuggestion(t('chat.suggestions.colorByAttribute', { name: mention }));
      }
      pushSuggestion(t('chat.suggestions.areaLabels', { name: mention }));
    } else if (geom.includes('line')) {
      pushSuggestion(t('chat.suggestions.colorByAttribute', { name: mention }));
    } else if (layer.layer_type === 'raster_geolens' || !geom) {
      pushSuggestion(t('chat.suggestions.adjustOpacity', { name: mention }));
    }
  }

  if (suggestions.length < 4) {
    pushSuggestion(t('chat.suggestions.addDataset'));
  }

  return suggestions.slice(0, 4);
}
