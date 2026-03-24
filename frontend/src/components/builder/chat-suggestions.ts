import type { TFunction } from 'i18next';
import type { MapLayerResponse } from '@/types/api';

/**
 * Generate geometry-aware and column-type-aware smart suggestions
 * for the chat empty state, based on current map layers.
 */

function isNumeric(type: string): boolean {
  const t = type.toLowerCase();
  return ['numeric', 'integer', 'float', 'double', 'real', 'int', 'bigint', 'smallint'].some(
    (k) => t.includes(k),
  );
}

function isText(type: string): boolean {
  const t = type.toLowerCase();
  return ['text', 'varchar', 'character', 'string'].some((k) => t.includes(k));
}

function isTemporal(type: string): boolean {
  const t = type.toLowerCase();
  return ['timestamp', 'date', 'time'].some((k) => t.includes(k));
}

function layerName(layer: MapLayerResponse): string {
  return layer.display_name ?? layer.dataset_name;
}

function mentionName(layer: MapLayerResponse): string {
  const name = layerName(layer);
  return name.includes(' ') ? `@[${name}]` : `@${name}`;
}

export function getSmartSuggestions(layers: MapLayerResponse[], t: TFunction): string[] {
  const suggestions: string[] = [];

  for (const layer of layers) {
    if (suggestions.length >= 4) break;

    const mention = mentionName(layer);
    const geom = (layer.dataset_geometry_type ?? '').toLowerCase();
    const cols = layer.dataset_column_info ?? [];
    const numericCols = cols.filter((c) => isNumeric(c.type));
    const textCols = cols.filter((c) => isText(c.type));
    const temporalCols = cols.filter((c) => isTemporal(c.type));

    // Geometry-specific suggestions (prioritize unstyled layers)
    if (geom.includes('point')) {
      if (!layer.style_config && suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.heatmap', { name: mention }));
      }
      if (numericCols.length > 0 && suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.sizeBy', { name: mention, column: numericCols[0].name }));
      }
      if (!layer.style_config && suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.cluster', { name: mention }));
      }
    } else if (geom.includes('polygon') || geom.includes('multipolygon')) {
      if (numericCols.length > 0 && !layer.style_config && suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.colorBy', { name: mention, column: numericCols[0].name }));
      }
      if (suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.areaLabels', { name: mention }));
      }
    } else if (geom.includes('line')) {
      if (numericCols.length > 0 && suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.varyWidth', { name: mention, column: numericCols[0].name }));
      }
    } else if (layer.layer_type === 'raster' || geom === '') {
      if (suggestions.length < 4) {
        suggestions.push(t('chat.suggestions.adjustOpacity', { name: mention }));
      }
    }

    // Column-type-aware suggestions
    if (numericCols.length > 0 && suggestions.length < 4) {
      suggestions.push(t('chat.suggestions.distribution', { name: mention, column: numericCols[0].name }));
    }
    if (textCols.length > 0 && suggestions.length < 4) {
      suggestions.push(t('chat.suggestions.categories', { name: mention, column: textCols[0].name }));
    }
    if (temporalCols.length > 0 && suggestions.length < 4) {
      suggestions.push(t('chat.suggestions.filterByDate', { name: mention }));
    }
  }

  // Always end with "Add another dataset" if room
  if (suggestions.length < 4) {
    suggestions.push(t('chat.suggestions.addDataset'));
  }

  return suggestions.slice(0, 4);
}
