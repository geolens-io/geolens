import type React from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

export type PluginAnchor = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

/** Fixed at registration time. */
type PluginPlacement =
  | { mode: 'floating'; anchor: PluginAnchor }
  | { mode: 'sidebar' };

export interface PluginContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
  /** Map-level terrain config; drives the synthetic "3D terrain" legend entry. */
  terrainConfig?: MapTerrainConfig | null;
  /** Map-level custom legend title; null/undefined means no heading override. */
  legendTitle?: string | null;
  /** Persists the legend title; null/empty clears it. Optional for read-only contexts. */
  onLegendTitleChange?: (title: string | null) => void;
  /**
   * Persist a per-entry legend label override onto a layer's
   * style_config.legendLabel. An empty string clears the override (falls back
   * to the layer display/dataset name).
   */
  onLegendLabelChange?: (layerId: string, label: string) => void;
}

export interface PluginDefinition {
  id: string;
  /** i18n key under the 'builder' namespace, e.g. 'plugins.measurement.label' */
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  placement: PluginPlacement;
  component: React.ComponentType<{ ctx: PluginContext }>;
  defaultVisible?: boolean;
}
