import type { FilterSpecification } from 'maplibre-gl';
import type { LabelConfig, MapLayerResponse, PopupConfig, StyleConfig } from '@/types/api';

export type BuilderActionSource = 'manual' | 'ai' | 'system';

interface BuilderActionBase {
  source?: BuilderActionSource;
}

export type BuilderLayerAction =
  | (BuilderActionBase & { type: 'set_filter'; layerId: string; expression: FilterSpecification | null })
  | (BuilderActionBase & { type: 'set_paint'; layerId: string; paint: Record<string, unknown> })
  | (BuilderActionBase & { type: 'set_style_config'; layerId: string; config: StyleConfig | null; paint: Record<string, unknown> })
  | (BuilderActionBase & { type: 'set_label'; layerId: string; config: LabelConfig | null })
  | (BuilderActionBase & { type: 'set_popup'; layerId: string; config: PopupConfig | null })
  | (BuilderActionBase & { type: 'set_layout'; layerId: string; layout: Record<string, unknown> })
  | (BuilderActionBase & { type: 'set_visibility'; layerId: string; visible?: boolean })
  | (BuilderActionBase & { type: 'set_opacity'; layerId: string; opacity: number })
  | (BuilderActionBase & { type: 'add_dataset'; datasetId: string })
  | (BuilderActionBase & { type: 'remove_layer'; layerId: string; persistence: 'server' | 'draft' })
  | (BuilderActionBase & { type: 'duplicate_rendering'; layerId: string })
  | (BuilderActionBase & { type: 'reorder_layers'; layers: MapLayerResponse[] })
  | (BuilderActionBase & { type: 'bind_dem_terrain'; layerId: string });

export type BuilderBasemapAction =
  | (BuilderActionBase & { type: 'set_basemap_labels'; visible: boolean })
  | (BuilderActionBase & { type: 'set_basemap_background'; color: string | null })
  | (BuilderActionBase & { type: 'set_basemap_position'; position: 'top' | 'bottom' })
  | (BuilderActionBase & { type: 'set_terrain_exaggeration'; exaggeration: number });

export type BuilderSettingsAction =
  | (BuilderActionBase & { type: 'toggle_widget'; widgetId: string })
  | (BuilderActionBase & { type: 'set_projection'; projection: 'mercator' | 'globe' });

export type BuilderMapAction = BuilderLayerAction | BuilderBasemapAction | BuilderSettingsAction;

export interface BuilderLayerActionHandlers {
  setFilter: (layerId: string, expression: FilterSpecification | null) => void;
  setPaint: (layerId: string, paint: Record<string, unknown>) => void;
  setStyleConfig: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  setLabel: (layerId: string, config: LabelConfig | null) => void;
  setPopup: (layerId: string, config: PopupConfig | null) => void;
  setLayout: (layerId: string, layout: Record<string, unknown>) => void;
  setVisibility: (layerId: string, visible?: boolean) => void;
  setOpacity: (layerId: string, opacity: number) => void;
  addDataset: (datasetId: string) => void;
  removePersistedLayer: (layerId: string) => void;
  removeDraftLayer: (layerId: string) => void;
  duplicateRendering: (layerId: string) => void;
  reorderLayers: (layers: MapLayerResponse[]) => void;
  bindDemTerrain: (layerId: string) => void;
}

export function dispatchBuilderLayerAction(
  action: BuilderLayerAction,
  handlers: BuilderLayerActionHandlers,
) {
  switch (action.type) {
    case 'set_filter':
      handlers.setFilter(action.layerId, action.expression);
      break;
    case 'set_paint':
      handlers.setPaint(action.layerId, action.paint);
      break;
    case 'set_style_config':
      handlers.setStyleConfig(action.layerId, action.config, action.paint);
      break;
    case 'set_label':
      handlers.setLabel(action.layerId, action.config);
      break;
    case 'set_popup':
      handlers.setPopup(action.layerId, action.config);
      break;
    case 'set_layout':
      handlers.setLayout(action.layerId, action.layout);
      break;
    case 'set_visibility':
      handlers.setVisibility(action.layerId, action.visible);
      break;
    case 'set_opacity':
      handlers.setOpacity(action.layerId, action.opacity);
      break;
    case 'add_dataset':
      handlers.addDataset(action.datasetId);
      break;
    case 'remove_layer':
      if (action.persistence === 'draft') {
        handlers.removeDraftLayer(action.layerId);
      } else {
        handlers.removePersistedLayer(action.layerId);
      }
      break;
    case 'duplicate_rendering':
      handlers.duplicateRendering(action.layerId);
      break;
    case 'reorder_layers':
      handlers.reorderLayers(action.layers);
      break;
    case 'bind_dem_terrain':
      handlers.bindDemTerrain(action.layerId);
      break;
  }
}
