import type React from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

/** Named positions where widgets can render */
export type WidgetSlot =
  | 'top-left'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-right'
  | 'sidebar-bottom'
  | 'map-overlay';

/** Context every widget receives */
export interface WidgetContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
}

/** A registered widget */
export interface WidgetDefinition {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  slot: WidgetSlot;
  component: React.ComponentType<{ ctx: WidgetContext }>;
  defaultVisible?: boolean;
}
