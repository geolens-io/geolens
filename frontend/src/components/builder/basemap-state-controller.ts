import type {
  MapBasemapConfig,
  MapBasemapVisibilityMode,
  MapSublayerOverride,
  MapTerrainConfig,
} from '@/types/api';
import {
  BLANK_BASEMAP_ID,
  DEFAULT_BASEMAP_CONFIG,
  hasVisibleBasemapStyle,
  normalizeBasemapConfig,
  resolveBasemapId,
} from '@/lib/basemap-utils';
import { normalizeTerrainExaggeration } from '@/components/builder/map-sync';

export type BuilderBasemapSublayerId =
  | 'basemap:roads'
  | 'basemap:labels'
  | 'basemap:buildings'
  | 'basemap:boundaries';

export interface BuilderBasemapSublayer {
  id: BuilderBasemapSublayerId;
  name: string;
  visible: boolean;
  opacity: number;
  kind: 'vector';
}

export interface BuilderBasemapStateInput {
  basemapStyle: string | null | undefined;
  showBasemapLabels: boolean | null | undefined;
  basemapConfig: MapBasemapConfig | null | undefined;
  terrainConfig: MapTerrainConfig | null | undefined;
}

export interface BuilderBasemapState {
  basemapStyle: string;
  showBasemapLabels: boolean;
  hasVisibleBasemap: boolean;
  config: MapBasemapConfig;
  terrainConfig: MapTerrainConfig | null;
  sublayers: BuilderBasemapSublayer[];
}

export interface BuilderBasemapPatch {
  basemapStyle?: string;
  showBasemapLabels?: boolean;
  basemapConfig?: MapBasemapConfig | null;
  terrainConfig?: MapTerrainConfig | null;
}

export const SUBLAYER_ID_OVERRIDE_KEY: Record<BuilderBasemapSublayerId, string> = {
  'basemap:roads': 'road',
  'basemap:labels': 'label',
  'basemap:buildings': 'building',
  'basemap:boundaries': 'boundary',
};

const DEFAULT_BASEMAP_STYLE = 'openfreemap-positron';

const DEFAULT_VISIBILITY: Record<BuilderBasemapSublayerId, boolean> = {
  'basemap:roads': true,
  'basemap:labels': true,
  'basemap:buildings': true,
  'basemap:boundaries': true,
};

function normalizedConfig(
  basemapConfig: MapBasemapConfig | null | undefined,
  showBasemapLabels: boolean,
): MapBasemapConfig {
  const config = normalizeBasemapConfig(basemapConfig, showBasemapLabels);
  return showBasemapLabels ? config : { ...config, label_mode: 'hidden' };
}

function normalizedTerrainConfig(
  terrainConfig: MapTerrainConfig | null | undefined,
): MapTerrainConfig | null {
  if (!terrainConfig) return null;
  return {
    ...terrainConfig,
    exaggeration: normalizeTerrainExaggeration(terrainConfig.exaggeration),
  };
}

function visibilityFromMode(mode: MapBasemapVisibilityMode | undefined): boolean {
  return mode !== 'hidden';
}

function modeFromVisible(visible: boolean): MapBasemapVisibilityMode {
  return visible ? 'full' : 'hidden';
}

function overrideOpacity(config: MapBasemapConfig, id: BuilderBasemapSublayerId): number {
  const key = SUBLAYER_ID_OVERRIDE_KEY[id];
  const value = config.sublayer_overrides?.[key]?.opacity;
  return typeof value === 'number' && Number.isFinite(value) ? value : 1;
}

function sublayersFromConfig(
  config: MapBasemapConfig,
  showBasemapLabels: boolean,
): BuilderBasemapSublayer[] {
  return [
    {
      id: 'basemap:roads',
      name: 'Roads',
      visible: visibilityFromMode(config.road_visibility),
      opacity: overrideOpacity(config, 'basemap:roads'),
      kind: 'vector',
    },
    {
      id: 'basemap:labels',
      name: 'Labels',
      visible: showBasemapLabels && visibilityFromMode(config.label_mode),
      opacity: overrideOpacity(config, 'basemap:labels'),
      kind: 'vector',
    },
    {
      id: 'basemap:buildings',
      name: 'Buildings',
      visible: config.building_visibility,
      opacity: overrideOpacity(config, 'basemap:buildings'),
      kind: 'vector',
    },
    {
      id: 'basemap:boundaries',
      name: 'Boundaries',
      visible: visibilityFromMode(config.boundary_visibility),
      opacity: overrideOpacity(config, 'basemap:boundaries'),
      kind: 'vector',
    },
  ];
}

export function createBuilderBasemapState(
  input: BuilderBasemapStateInput,
): BuilderBasemapState {
  const showBasemapLabels = input.showBasemapLabels ?? true;
  const basemapStyle = resolveBasemapId(input.basemapStyle || DEFAULT_BASEMAP_STYLE);
  const config = normalizedConfig(input.basemapConfig, showBasemapLabels);
  return {
    basemapStyle,
    showBasemapLabels,
    hasVisibleBasemap: hasVisibleBasemapStyle(basemapStyle),
    config,
    terrainConfig: normalizedTerrainConfig(input.terrainConfig),
    sublayers: sublayersFromConfig(config, showBasemapLabels),
  };
}

export function swapBasemapPreset(
  state: BuilderBasemapState,
  presetId: string,
): BuilderBasemapPatch {
  return {
    basemapStyle: presetId,
    showBasemapLabels: state.config.label_mode !== 'hidden',
    basemapConfig: state.config,
  };
}

export function removeBasemap(state: BuilderBasemapState): BuilderBasemapPatch {
  return {
    basemapStyle: BLANK_BASEMAP_ID,
    showBasemapLabels: state.showBasemapLabels,
    basemapConfig: state.config,
  };
}

export function setBasemapPosition(
  state: BuilderBasemapState,
  position: NonNullable<MapBasemapConfig['basemap_position']>,
): BuilderBasemapPatch {
  return { basemapConfig: { ...state.config, basemap_position: position } };
}

export function setBasemapMasterOpacity(
  state: BuilderBasemapState,
  opacity: number,
): BuilderBasemapPatch {
  const safeOpacity = Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : DEFAULT_BASEMAP_CONFIG.opacity;
  return { basemapConfig: { ...state.config, opacity: safeOpacity } };
}

export function setBasemapBackgroundColor(
  state: BuilderBasemapState,
  color: string | null,
): BuilderBasemapPatch {
  return { basemapConfig: { ...state.config, background_color: color } };
}

export function toggleBasemapSublayerVisibility(
  state: BuilderBasemapState,
  sublayerId: string,
): BuilderBasemapPatch {
  const id = sublayerId as BuilderBasemapSublayerId;
  const current = state.sublayers.find((sublayer) => sublayer.id === id);
  if (!current) return {};
  const nextVisible = !current.visible;

  if (id === 'basemap:roads') {
    return {
      basemapConfig: { ...state.config, road_visibility: modeFromVisible(nextVisible) },
    };
  }
  if (id === 'basemap:labels') {
    return {
      showBasemapLabels: nextVisible,
      basemapConfig: { ...state.config, label_mode: modeFromVisible(nextVisible) },
    };
  }
  if (id === 'basemap:buildings') {
    return {
      basemapConfig: { ...state.config, building_visibility: nextVisible },
    };
  }
  if (id === 'basemap:boundaries') {
    return {
      basemapConfig: { ...state.config, boundary_visibility: modeFromVisible(nextVisible) },
    };
  }
  return {};
}

export function setBasemapLabelsVisible(
  state: BuilderBasemapState,
  visible: boolean,
): BuilderBasemapPatch {
  return {
    showBasemapLabels: visible,
    basemapConfig: { ...state.config, label_mode: modeFromVisible(visible) },
  };
}

function pruneOverride(override: MapSublayerOverride): MapSublayerOverride | null {
  return Object.values(override).every((value) => value == null) ? null : override;
}

export function updateBasemapSublayerOverride(
  state: BuilderBasemapState,
  sublayerId: string,
  field: keyof MapSublayerOverride,
  value: string | number | null,
): BuilderBasemapPatch {
  const key = SUBLAYER_ID_OVERRIDE_KEY[sublayerId as BuilderBasemapSublayerId];
  if (!key) return {};
  const currentOverrides = state.config.sublayer_overrides ?? {};
  const currentOverride = currentOverrides[key] ?? {};
  const nextOverride = pruneOverride({ ...currentOverride, [field]: value });
  const nextOverrides = { ...currentOverrides };
  if (nextOverride) {
    nextOverrides[key] = nextOverride;
  } else {
    delete nextOverrides[key];
  }
  return {
    basemapConfig: {
      ...state.config,
      sublayer_overrides: Object.keys(nextOverrides).length > 0 ? nextOverrides : null,
    },
  };
}

export function setBasemapSublayerOpacity(
  state: BuilderBasemapState,
  sublayerId: string,
  opacity: number,
): BuilderBasemapPatch {
  const safeOpacity = Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 1;
  return updateBasemapSublayerOverride(state, sublayerId, 'opacity', safeOpacity);
}

export function resetBasemapSublayer(
  state: BuilderBasemapState,
  sublayerId: string,
): BuilderBasemapPatch {
  const key = SUBLAYER_ID_OVERRIDE_KEY[sublayerId as BuilderBasemapSublayerId];
  if (!key) return {};
  const nextOverrides = { ...(state.config.sublayer_overrides ?? {}) };
  delete nextOverrides[key];

  let nextConfig: MapBasemapConfig = {
    ...state.config,
    sublayer_overrides: Object.keys(nextOverrides).length > 0 ? nextOverrides : null,
  };
  let showBasemapLabels: boolean | undefined;

  if (sublayerId in DEFAULT_VISIBILITY) {
    if (sublayerId === 'basemap:roads') {
      nextConfig = { ...nextConfig, road_visibility: 'full' };
    } else if (sublayerId === 'basemap:labels') {
      showBasemapLabels = true;
      nextConfig = { ...nextConfig, label_mode: 'full' };
    } else if (sublayerId === 'basemap:buildings') {
      nextConfig = { ...nextConfig, building_visibility: true };
    } else if (sublayerId === 'basemap:boundaries') {
      nextConfig = { ...nextConfig, boundary_visibility: 'full' };
    }
  }

  return { basemapConfig: nextConfig, showBasemapLabels };
}

export function resetBasemapAppearance(): BuilderBasemapPatch {
  return { basemapConfig: null };
}

export function setTerrainExaggeration(
  terrainConfig: MapTerrainConfig | null | undefined,
  value: number,
): BuilderBasemapPatch {
  const exaggeration = normalizeTerrainExaggeration(value);
  return {
    terrainConfig: terrainConfig
      ? { ...terrainConfig, exaggeration }
      : { enabled: false, source_dataset_id: null, exaggeration },
  };
}
