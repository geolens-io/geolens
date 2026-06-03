import type { MapLayerResponse } from '@/types/api';

/**
 * Generate geometry-aware suggestions for the chat empty state.
 * Simple fixed suggestions per geometry type — no column introspection.
 *
 * Phase 1135 AI-05: extended with optional `viewport` parameter for
 * viewport-aware suggestion priority (selected layer + zoom-gated nearby features).
 * Callers that omit viewport receive the unchanged geometry-type-only list.
 */

export interface ViewportContext {
  zoom: number;
  bounds: [number, number, number, number]; // [west, south, east, north] WGS84
  selectedLayerName?: string;
}

function mentionName(layer: MapLayerResponse): string {
  return formatLayerNameForMention(layer.display_name ?? layer.dataset_name);
}

function formatLayerNameForMention(name: string): string {
  return name.includes(' ') ? `@[${name}]` : `@${name}`;
}

type AnyTFunction = (key: string, options?: Record<string, unknown>) => string;

function hasVectorGeometry(layers: MapLayerResponse[]): boolean {
  for (const layer of layers) {
    const geom = (layer.dataset_geometry_type ?? '').toLowerCase();
    if (geom.includes('point') || geom.includes('line') || geom.includes('polygon')) return true;
  }
  return false;
}

export function getSmartSuggestions(
  layers: MapLayerResponse[],
  t: AnyTFunction,
  viewport?: ViewportContext,
): string[] {
  const suggestions: string[] = [];
  const pushSuggestion = (suggestion: string) => {
    if (suggestions.length < 4 && !suggestions.includes(suggestion)) {
      suggestions.push(suggestion);
    }
  };

  // Priority 1: selected-layer summarize (viewport-aware)
  if (viewport?.selectedLayerName) {
    const mention = formatLayerNameForMention(viewport.selectedLayerName);
    pushSuggestion(t('chat.suggestions.summarizeLayer', { name: mention }));
  }

  // Priority 2: nearby features when zoomed in over vector content
  if (viewport && viewport.zoom >= 12 && hasVectorGeometry(layers)) {
    pushSuggestion(t('chat.suggestions.nearbyFeatures'));
  }

  // Priority 3: existing per-layer geometry-type suggestions (unchanged shape)
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

  // Priority 4: addDataset fallback
  if (suggestions.length < 4) {
    pushSuggestion(t('chat.suggestions.addDataset'));
  }

  return suggestions.slice(0, 4);
}
