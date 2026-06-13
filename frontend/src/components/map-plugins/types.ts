import type React from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

/** Anchor positions for floating plugins */
export type PluginAnchor = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

/** Placement configuration -- fixed at registration time */
export type PluginPlacement =
  | { mode: 'floating'; anchor: PluginAnchor }
  | { mode: 'sidebar' };  // sidebar plugins render in the builder's left sidebar

/** Context every plugin receives */
export interface PluginContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
  /** Map-level terrain config; drives the synthetic "3D terrain" legend entry. */
  terrainConfig?: MapTerrainConfig | null;
  /**
   * Map-level custom legend title (ENH-06). Null/undefined renders the legend
   * without a heading override.
   */
  legendTitle?: string | null;
  /**
   * Persist a new map-level legend title. Null/empty clears it. Optional so
   * read-only plugin contexts (e.g. tests) can omit it.
   */
  onLegendTitleChange?: (title: string | null) => void;
  /**
   * Persist a per-entry legend label override onto a layer's
   * style_config.legendLabel. An empty string clears the override (falls back
   * to the layer display/dataset name).
   */
  onLegendLabelChange?: (layerId: string, label: string) => void;
}

/** A registered plugin */
export interface PluginDefinition {
  id: string;
  /** i18n key under the 'builder' namespace, e.g. 'plugins.measurement.label' */
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  placement: PluginPlacement;
  component: React.ComponentType<{ ctx: PluginContext }>;
  defaultVisible?: boolean;
}
