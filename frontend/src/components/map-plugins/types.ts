import type React from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

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
