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

// fix(#832): each suggestion pairs a plain-name label for display with the
// mention-markup payload inserted on click. The label is built from the
// original layer name rather than regex-stripped from the payload, which is
// lossy for names containing "]" (PR #853 review: "@[A] B]" -> "A B]").
export interface ChatSuggestion {
  /** Visible/accessible chip text, built with the plain layer name. */
  label: string;
  /** Raw prompt inserted into the chat input, with `@[...]` mention markup. */
  payload: string;
}

function layerName(layer: MapLayerResponse): string {
  return layer.display_name ?? layer.dataset_name;
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
): ChatSuggestion[] {
  const suggestions: ChatSuggestion[] = [];
  const pushSuggestion = (suggestion: ChatSuggestion) => {
    if (suggestions.length < 4 && !suggestions.some((s) => s.payload === suggestion.payload)) {
      suggestions.push(suggestion);
    }
  };
  const namedSuggestion = (key: string, name: string): ChatSuggestion => ({
    label: t(key, { name }),
    payload: t(key, { name: formatLayerNameForMention(name) }),
  });
  const plainSuggestion = (key: string): ChatSuggestion => {
    const text = t(key);
    return { label: text, payload: text };
  };

  // Priority 1: selected-layer summarize (viewport-aware)
  if (viewport?.selectedLayerName) {
    pushSuggestion(namedSuggestion('chat.suggestions.summarizeLayer', viewport.selectedLayerName));
  }

  // Priority 2: nearby features when zoomed in over vector content
  if (viewport && viewport.zoom >= 12 && hasVectorGeometry(layers)) {
    pushSuggestion(plainSuggestion('chat.suggestions.nearbyFeatures'));
  }

  // Priority 3: existing per-layer geometry-type suggestions (unchanged shape)
  for (const layer of layers) {
    if (suggestions.length >= 4) break;

    const name = layerName(layer);
    const geom = (layer.dataset_geometry_type ?? '').toLowerCase();

    if (geom.includes('point')) {
      pushSuggestion(namedSuggestion('chat.suggestions.colorByAttribute', name));
    } else if (geom.includes('polygon') || geom.includes('multipolygon')) {
      if (!layer.style_config) {
        pushSuggestion(namedSuggestion('chat.suggestions.colorByAttribute', name));
      }
      pushSuggestion(namedSuggestion('chat.suggestions.areaLabels', name));
    } else if (geom.includes('line')) {
      pushSuggestion(namedSuggestion('chat.suggestions.colorByAttribute', name));
    } else if (layer.layer_type === 'raster_geolens' || !geom) {
      pushSuggestion(namedSuggestion('chat.suggestions.adjustOpacity', name));
    }
  }

  // Priority 4: addDataset fallback
  if (suggestions.length < 4) {
    pushSuggestion(plainSuggestion('chat.suggestions.addDataset'));
  }

  return suggestions.slice(0, 4);
}
