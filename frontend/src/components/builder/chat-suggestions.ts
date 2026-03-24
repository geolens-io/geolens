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

export function getSmartSuggestions(layers: MapLayerResponse[]): string[] {
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
        suggestions.push(`Create a heatmap of ${mention}`);
      }
      if (numericCols.length > 0 && suggestions.length < 4) {
        suggestions.push(`Size ${mention} by ${numericCols[0].name}`);
      }
      if (!layer.style_config && suggestions.length < 4) {
        suggestions.push(`Cluster ${mention} points`);
      }
    } else if (geom.includes('polygon') || geom.includes('multipolygon')) {
      if (numericCols.length > 0 && !layer.style_config && suggestions.length < 4) {
        suggestions.push(`Color ${mention} by ${numericCols[0].name}`);
      }
      if (suggestions.length < 4) {
        suggestions.push(`Show area labels on ${mention}`);
      }
    } else if (geom.includes('line')) {
      if (numericCols.length > 0 && suggestions.length < 4) {
        suggestions.push(`Vary ${mention} width by ${numericCols[0].name}`);
      }
    } else if (layer.layer_type === 'raster' || geom === '') {
      if (suggestions.length < 4) {
        suggestions.push(`Adjust ${mention} opacity`);
      }
    }

    // Column-type-aware suggestions
    if (numericCols.length > 0 && suggestions.length < 4) {
      suggestions.push(`Show distribution of ${numericCols[0].name} in ${mention}`);
    }
    if (textCols.length > 0 && suggestions.length < 4) {
      suggestions.push(`Color ${mention} by ${textCols[0].name} categories`);
    }
    if (temporalCols.length > 0 && suggestions.length < 4) {
      suggestions.push(`Filter ${mention} by date range`);
    }
  }

  // Always end with "Add another dataset" if room
  if (suggestions.length < 4) {
    suggestions.push('Add another dataset');
  }

  return suggestions.slice(0, 4);
}
