import type React from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

/** Anchor positions for floating widgets */
export type WidgetAnchor = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

/** Placement configuration -- fixed at registration time */
export type WidgetPlacement =
  | { mode: 'floating'; anchor: WidgetAnchor }
  | { mode: 'sidebar' };

/** Context every widget receives */
export interface WidgetContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
  /** Basemap state — provided by the builder for basemap widget */
  basemap?: {
    value: string;
    onChange: (id: string) => void;
    showLabels: boolean;
    onToggleLabels: (show: boolean) => void;
    onDirty: () => void;
  };
}

/** A registered widget */
export interface WidgetDefinition {
  id: string;
  /** i18n key under the 'builder' namespace, e.g. 'widgets.measurement.label' */
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  placement: WidgetPlacement;
  component: React.ComponentType<{ ctx: WidgetContext }>;
  defaultVisible?: boolean;
}
