import type {
  LabelConfig,
  MapBasemapConfig,
  MapLayerResponse,
  MapTerrainConfig,
  PopupConfig,
  StyleConfig,
} from '@/types/api';
import { normalizeBasemapConfig } from '@/lib/basemap-utils';

export const MAP_STACK_GROUP_ORDER = [
  'surface',
  'relief',
  'basemap',
  'data',
  'labels',
  'interactions',
] as const;

export type MapStackGroupId = typeof MAP_STACK_GROUP_ORDER[number];

export type MapStackRole =
  | 'surface-background'
  | 'surface-terrain'
  | 'relief-hillshade'
  | 'relief-color'
  | 'relief-contour'
  | 'basemap-preset'
  | 'basemap-labels'
  | 'data-layer'
  | 'data-labels'
  | 'interaction-popups'
  | 'interaction-widgets';

export type MapStackBadgeTone = 'neutral' | 'muted' | 'info' | 'success' | 'warning' | 'danger';

export interface MapStackBadge {
  label: string;
  tone: MapStackBadgeTone;
}

export type MapStackTerrainSourceStatus =
  | 'active'
  | 'available'
  | 'disabled'
  | 'fallback'
  | 'missing';

export interface MapStackDuplicateMetadata {
  datasetKey: string;
  datasetOccurrence: number;
  datasetCount: number;
  nameOccurrence: number;
  nameCount: number;
  disambiguationLabel: string | null;
}

export interface MapStackEntryMetadata {
  drawOrder: number;
  source: 'derived' | 'map-layer' | 'basemap' | 'terrain';
  sourceLayerId?: string;
  sourceDatasetId?: string | null;
  datasetName?: string;
  datasetRecordType?: string | null;
  datasetFeatureCount?: number | null;
  geometryType?: string | null;
  layerType?: string | null;
  renderMode?: string | null;
  layerVisible?: boolean;
  legendVisible?: boolean;
  labelColumn?: string | null;
  popupEnabled?: boolean;
  duplicate?: MapStackDuplicateMetadata;
  terrain?: {
    enabled: boolean;
    exaggeration: number;
    sourceDatasetId: string | null;
    sourceLayerId: string | null;
    sourceStatus: MapStackTerrainSourceStatus;
    verticalUnits: string | null;
  };
  basemap?: {
    style: string;
    sublayer: 'preset' | 'labels';
    labelsVisible?: boolean;
    config?: MapBasemapConfig | null;
    futureControl: boolean;
  };
  widgets?: string[];
}

export interface MapStackEntry {
  id: string;
  groupId: MapStackGroupId;
  role: MapStackRole;
  title: string;
  subtitle: string | null;
  order: number;
  orderLabel: string;
  visible: boolean;
  locked: boolean;
  badges: MapStackBadge[];
  metadata: MapStackEntryMetadata;
}

export interface MapStackGroup {
  id: MapStackGroupId;
  title: string;
  description: string;
  order: number;
  entries: MapStackEntry[];
}

export interface MapStackMapInput {
  basemap_style?: string | null;
  show_basemap_labels?: boolean | null;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  layers?: MapLayerResponse[];
  widgets?: string[] | null;
}

interface IndexedLayer {
  layer: MapLayerResponse;
  originalIndex: number;
}

interface LayerDuplicateIndex {
  byLayerId: Map<string, MapStackDuplicateMetadata>;
}

const GROUP_TITLES: Record<MapStackGroupId, { title: string; description: string }> = {
  surface: {
    title: 'Surface',
    description: 'Scene foundation, terrain, and elevation sources.',
  },
  relief: {
    title: 'Relief',
    description: 'DEM-derived visual overlays such as hillshade, contours, and color relief.',
  },
  basemap: {
    title: 'Basemap',
    description: 'Base map preset and future sublayer appearance controls.',
  },
  data: {
    title: 'Data',
    description: 'User-added thematic layers.',
  },
  labels: {
    title: 'Labels',
    description: 'Basemap and data label layers drawn above data geometry.',
  },
  interactions: {
    title: 'Interactions',
    description: 'Popup and widget affordances surfaced with the map.',
  },
};

const GROUP_ORDER_BASE: Record<MapStackGroupId, number> = {
  surface: 0,
  relief: 1000,
  basemap: 2000,
  data: 3000,
  labels: 4000,
  interactions: 5000,
};

const DEM_RECORD_TYPES = new Set(['raster_dataset', 'vrt_dataset']);

function createEmptyGroups(): MapStackGroup[] {
  return MAP_STACK_GROUP_ORDER.map((id, index) => ({
    id,
    title: GROUP_TITLES[id].title,
    description: GROUP_TITLES[id].description,
    order: index,
    entries: [],
  }));
}

function groupFor(groups: MapStackGroup[], id: MapStackGroupId) {
  return groups[MAP_STACK_GROUP_ORDER.indexOf(id)];
}

function sortLayers(layers: MapLayerResponse[]): IndexedLayer[] {
  return layers
    .map((layer, originalIndex) => ({ layer, originalIndex }))
    .sort((a, b) => {
      const sortDelta = a.layer.sort_order - b.layer.sort_order;
      return sortDelta === 0 ? a.originalIndex - b.originalIndex : sortDelta;
    });
}

function displayLayerName(layer: MapLayerResponse) {
  return layer.display_name || layer.dataset_name || layer.dataset_table_name || 'Untitled layer';
}

function renderMode(styleConfig: StyleConfig | null | undefined): string | null {
  const mode = styleConfig?.render_mode;
  return typeof mode === 'string' && mode.length > 0 ? mode : null;
}

function labelColumn(labelConfig: LabelConfig | null | undefined) {
  const column = labelConfig?.column;
  return typeof column === 'string' && column.trim().length > 0 ? column : null;
}

function popupEnabled(popupConfig: PopupConfig | null | undefined) {
  return popupConfig?.enabled === true;
}

function isTerrainCapableDemLayer(layer: MapLayerResponse) {
  return layer.is_dem === true && DEM_RECORD_TYPES.has(String(layer.dataset_record_type ?? ''));
}

function isDemVisualLayer(layer: MapLayerResponse) {
  return layer.is_dem === true;
}

function reliefRole(layer: MapLayerResponse): Extract<MapStackRole, `relief-${string}`> {
  const mode = renderMode(layer.style_config);
  if (mode === 'hillshade') return 'relief-hillshade';
  if (mode === 'contour') return 'relief-contour';
  return 'relief-color';
}

function typeBadge(layer: MapLayerResponse): MapStackBadge {
  const mode = renderMode(layer.style_config);
  if (mode === 'hillshade') return { label: 'Hillshade', tone: 'info' };
  if (mode === 'heatmap') return { label: 'Heatmap', tone: 'info' };
  if (mode === 'symbol') return { label: 'Symbol', tone: 'info' };
  if (layer.is_dem) return { label: 'DEM', tone: 'info' };
  if (layer.layer_type !== 'raster_geolens' && !layer.dataset_geometry_type) {
    return { label: 'Unsupported', tone: 'warning' };
  }
  if (layer.dataset_geometry_type) return { label: layer.dataset_geometry_type, tone: 'neutral' };
  if (layer.layer_type === 'raster_geolens') return { label: 'Raster', tone: 'neutral' };
  return { label: 'Layer', tone: 'neutral' };
}

function layerBadges(layer: MapLayerResponse, duplicate?: MapStackDuplicateMetadata): MapStackBadge[] {
  const badges = [typeBadge(layer)];
  if (!layer.visible) badges.push({ label: 'Hidden', tone: 'muted' });
  if (layer.show_in_legend === false) badges.push({ label: 'Legend hidden', tone: 'muted' });
  if (labelColumn(layer.label_config)) badges.push({ label: 'Labels', tone: 'success' });
  if (popupEnabled(layer.popup_config)) badges.push({ label: 'Popup', tone: 'success' });
  if (duplicate?.disambiguationLabel) {
    badges.push({ label: duplicate.disambiguationLabel, tone: 'warning' });
  }
  return badges;
}

function dataOrderLabel(indexFromTop: number, total: number) {
  const position = indexFromTop + 1;
  if (total === 1) return 'Data 1 of 1';
  if (position === 1) return `Data ${position} of ${total} (top)`;
  if (position === total) return `Data ${position} of ${total} (bottom)`;
  return `Data ${position} of ${total}`;
}

function reliefOrderLabel(indexFromBottom: number, total: number) {
  const position = indexFromBottom + 1;
  if (total === 1) return 'Relief 1 of 1';
  if (position === 1) return `Relief ${position} of ${total} (bottom)`;
  if (position === total) return `Relief ${position} of ${total} (top)`;
  return `Relief ${position} of ${total}`;
}

function dataLabelOrderLabel(indexFromBottom: number, total: number) {
  const position = indexFromBottom + 1;
  if (total === 1) return 'Data labels 1 of 1';
  if (position === total) return `Data labels ${position} of ${total} (top)`;
  return `Data labels ${position} of ${total}`;
}

function stableDatasetKey(layer: MapLayerResponse) {
  return layer.dataset_id || layer.dataset_table_name || layer.id;
}

function duplicateIndex(orderedLayers: IndexedLayer[]): LayerDuplicateIndex {
  const datasetCounts = new Map<string, number>();
  const nameCounts = new Map<string, number>();
  for (const { layer } of orderedLayers) {
    const datasetKey = stableDatasetKey(layer);
    const name = displayLayerName(layer);
    datasetCounts.set(datasetKey, (datasetCounts.get(datasetKey) ?? 0) + 1);
    nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1);
  }

  const datasetOccurrences = new Map<string, number>();
  const nameOccurrences = new Map<string, number>();
  const byLayerId = new Map<string, MapStackDuplicateMetadata>();

  for (const { layer } of orderedLayers) {
    const datasetKey = stableDatasetKey(layer);
    const name = displayLayerName(layer);
    const datasetOccurrence = (datasetOccurrences.get(datasetKey) ?? 0) + 1;
    const nameOccurrence = (nameOccurrences.get(name) ?? 0) + 1;
    datasetOccurrences.set(datasetKey, datasetOccurrence);
    nameOccurrences.set(name, nameOccurrence);

    const datasetCount = datasetCounts.get(datasetKey) ?? 1;
    const nameCount = nameCounts.get(name) ?? 1;
    const duplicateCount = Math.max(datasetCount, nameCount);
    const copyOccurrence = datasetCount > 1 ? datasetOccurrence : nameOccurrence;
    const copyCount = datasetCount > 1 ? datasetCount : nameCount;
    byLayerId.set(layer.id, {
      datasetKey,
      datasetOccurrence,
      datasetCount,
      nameOccurrence,
      nameCount,
      disambiguationLabel: duplicateCount > 1 ? `Copy ${copyOccurrence} of ${copyCount}` : null,
    });
  }

  return { byLayerId };
}

function layerMetadata(
  layer: MapLayerResponse,
  drawOrder: number,
  duplicate?: MapStackDuplicateMetadata,
): MapStackEntryMetadata {
  return {
    drawOrder,
    source: 'map-layer',
    sourceLayerId: layer.id,
    sourceDatasetId: layer.dataset_id,
    datasetName: layer.dataset_name,
    datasetRecordType: layer.dataset_record_type ?? null,
    datasetFeatureCount: layer.dataset_feature_count ?? null,
    geometryType: layer.dataset_geometry_type ?? null,
    layerType: layer.layer_type ?? null,
    renderMode: renderMode(layer.style_config),
    layerVisible: layer.visible,
    legendVisible: layer.show_in_legend !== false,
    labelColumn: labelColumn(layer.label_config),
    popupEnabled: popupEnabled(layer.popup_config),
    duplicate,
  };
}

function makeSurfaceEntries(
  groups: MapStackGroup[],
  orderedLayers: IndexedLayer[],
  terrainConfig: MapTerrainConfig | null,
) {
  const surface = groupFor(groups, 'surface');
  surface.entries.push({
    id: 'surface:background',
    groupId: 'surface',
    role: 'surface-background',
    title: 'Base background',
    subtitle: 'Draws below terrain, basemap, relief, and data.',
    order: GROUP_ORDER_BASE.surface,
    orderLabel: 'Surface foundation',
    visible: true,
    locked: true,
    badges: [{ label: 'Background', tone: 'neutral' }],
    metadata: {
      drawOrder: GROUP_ORDER_BASE.surface,
      source: 'derived',
    },
  });

  const demLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter(isTerrainCapableDemLayer);
  if (demLayers.length === 0 && !terrainConfig?.source_dataset_id) return;

  const configuredSourceId = terrainConfig?.source_dataset_id ?? null;
  const selectedLayer = configuredSourceId
    ? demLayers.find((layer) => layer.dataset_id === configuredSourceId) ?? null
    : demLayers[0] ?? null;
  const fallbackLayer = !selectedLayer && demLayers.length > 0 ? demLayers[0] : null;
  const sourceLayer = selectedLayer ?? fallbackLayer;
  const sourceStatus: MapStackTerrainSourceStatus = terrainConfig?.enabled
    ? selectedLayer
      ? 'active'
      : fallbackLayer
        ? 'fallback'
        : 'missing'
    : configuredSourceId
      ? selectedLayer
        ? 'disabled'
        : 'missing'
      : 'available';
  const enabled = terrainConfig?.enabled === true && sourceStatus !== 'missing';
  const title = sourceLayer ? displayLayerName(sourceLayer) : 'Terrain source missing';
  const subtitle = sourceLayer
    ? `Elevation source${enabled ? `, ${terrainConfig?.exaggeration ?? 1}x exaggeration` : ''}`
    : configuredSourceId
      ? `Saved source ${configuredSourceId} is unavailable`
      : 'No DEM source selected';

  surface.entries.push({
    id: 'surface:terrain',
    groupId: 'surface',
    role: 'surface-terrain',
    title,
    subtitle,
    order: GROUP_ORDER_BASE.surface + 100,
    orderLabel: 'Surface terrain',
    visible: enabled,
    locked: false,
    badges: [
      { label: 'Terrain', tone: enabled ? 'success' : 'muted' },
      ...(sourceStatus === 'fallback' ? [{ label: 'Fallback source', tone: 'warning' } as const] : []),
      ...(sourceStatus === 'missing' ? [{ label: 'Missing source', tone: 'warning' } as const] : []),
    ],
    metadata: {
      drawOrder: GROUP_ORDER_BASE.surface + 100,
      source: 'terrain',
      sourceLayerId: sourceLayer?.id,
      sourceDatasetId: sourceLayer?.dataset_id ?? configuredSourceId,
      datasetName: sourceLayer?.dataset_name,
      datasetRecordType: sourceLayer?.dataset_record_type ?? null,
      datasetFeatureCount: sourceLayer?.dataset_feature_count ?? null,
      geometryType: sourceLayer?.dataset_geometry_type ?? null,
      layerType: sourceLayer?.layer_type ?? null,
      terrain: {
        enabled,
        exaggeration: terrainConfig?.exaggeration ?? 1,
        sourceDatasetId: sourceLayer?.dataset_id ?? configuredSourceId,
        sourceLayerId: sourceLayer?.id ?? null,
        sourceStatus,
        verticalUnits: sourceLayer?.dem_vertical_units ?? null,
      },
    },
  });
}

function makeReliefEntries(
  groups: MapStackGroup[],
  orderedLayers: IndexedLayer[],
  duplicates: LayerDuplicateIndex,
) {
  const reliefLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter(isDemVisualLayer);
  const relief = groupFor(groups, 'relief');
  [...reliefLayers].reverse().forEach((layer, indexFromBottom) => {
    const drawOrder = GROUP_ORDER_BASE.relief + indexFromBottom;
    const duplicate = duplicates.byLayerId.get(layer.id);
    relief.entries.push({
      id: `relief:${layer.id}`,
      groupId: 'relief',
      role: reliefRole(layer),
      title: displayLayerName(layer),
      subtitle: layer.dataset_name,
      order: drawOrder,
      orderLabel: reliefOrderLabel(indexFromBottom, reliefLayers.length),
      visible: layer.visible,
      locked: false,
      badges: layerBadges(layer, duplicate),
      metadata: layerMetadata(layer, drawOrder, duplicate),
    });
  });
}

function makeBasemapEntries(groups: MapStackGroup[], map: MapStackMapInput) {
  const basemap = groupFor(groups, 'basemap');
  const style = map.basemap_style || 'default';
  const config = normalizeBasemapConfig(map.basemap_config, map.show_basemap_labels ?? true);
  basemap.entries.push({
    id: `basemap:preset:${style}`,
    groupId: 'basemap',
    role: 'basemap-preset',
    title: 'Basemap preset',
    subtitle: style,
    order: GROUP_ORDER_BASE.basemap,
    orderLabel: 'Basemap foundation',
    visible: true,
    locked: false,
    badges: [
      { label: style, tone: 'neutral' },
      { label: 'Preset', tone: 'muted' },
      ...(config.land_water_tone !== 'default'
        ? [{ label: config.land_water_tone, tone: 'info' } as const]
        : []),
    ],
    metadata: {
      drawOrder: GROUP_ORDER_BASE.basemap,
      source: 'basemap',
      basemap: {
        style,
        sublayer: 'preset',
        config,
        futureControl: false,
      },
    },
  });
}

function makeDataEntries(
  groups: MapStackGroup[],
  orderedLayers: IndexedLayer[],
  duplicates: LayerDuplicateIndex,
) {
  const dataLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter((layer) => !isDemVisualLayer(layer));
  const data = groupFor(groups, 'data');
  [...dataLayers].reverse().forEach((layer, indexFromBottom) => {
    const indexFromTop = dataLayers.length - indexFromBottom - 1;
    const drawOrder = GROUP_ORDER_BASE.data + indexFromBottom;
    const duplicate = duplicates.byLayerId.get(layer.id);
    data.entries.push({
      id: `data:${layer.id}`,
      groupId: 'data',
      role: 'data-layer',
      title: displayLayerName(layer),
      subtitle: layer.display_name ? layer.dataset_name : layer.dataset_table_name,
      order: drawOrder,
      orderLabel: dataOrderLabel(indexFromTop, dataLayers.length),
      visible: layer.visible,
      locked: false,
      badges: layerBadges(layer, duplicate),
      metadata: layerMetadata(layer, drawOrder, duplicate),
    });
  });
}

function makeLabelEntries(
  groups: MapStackGroup[],
  orderedLayers: IndexedLayer[],
  map: MapStackMapInput,
  duplicates: LayerDuplicateIndex,
) {
  const labels = groupFor(groups, 'labels');
  const style = map.basemap_style || 'default';
  const config = normalizeBasemapConfig(map.basemap_config, map.show_basemap_labels ?? true);
  const showBasemapLabels = config.label_mode !== 'hidden';
  labels.entries.push({
    id: 'labels:basemap',
    groupId: 'labels',
    role: 'basemap-labels',
    title: 'Basemap labels',
    subtitle: showBasemapLabels
      ? config.label_mode === 'subtle'
        ? 'Subtle labels'
        : 'Draw above data geometry and below data labels.'
      : 'Hidden by map setting.',
    order: GROUP_ORDER_BASE.labels,
    orderLabel: 'Labels: basemap labels',
    visible: showBasemapLabels,
    locked: false,
    badges: [
      { label: 'Labels', tone: showBasemapLabels ? 'success' : 'muted' },
      ...(showBasemapLabels ? [] : [{ label: 'Hidden', tone: 'muted' } as const]),
    ],
    metadata: {
      drawOrder: GROUP_ORDER_BASE.labels,
      source: 'basemap',
      basemap: {
        style,
        sublayer: 'labels',
        labelsVisible: showBasemapLabels,
        config,
        futureControl: false,
      },
    },
  });

  const labelLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter((layer) => !isDemVisualLayer(layer) && labelColumn(layer.label_config));
  [...labelLayers].reverse().forEach((layer, indexFromBottom) => {
    const drawOrder = GROUP_ORDER_BASE.labels + 100 + indexFromBottom;
    const duplicate = duplicates.byLayerId.get(layer.id);
    labels.entries.push({
      id: `labels:data:${layer.id}`,
      groupId: 'labels',
      role: 'data-labels',
      title: `${displayLayerName(layer)} labels`,
      subtitle: `Column: ${labelColumn(layer.label_config)}`,
      order: drawOrder,
      orderLabel: dataLabelOrderLabel(indexFromBottom, labelLayers.length),
      visible: layer.visible,
      locked: false,
      badges: [
        { label: 'Data labels', tone: 'success' },
        ...(layer.visible ? [] : [{ label: 'Hidden', tone: 'muted' } as const]),
        ...(duplicate?.disambiguationLabel
          ? [{ label: duplicate.disambiguationLabel, tone: 'warning' } as const]
          : []),
      ],
      metadata: layerMetadata(layer, drawOrder, duplicate),
    });
  });
}

function makeInteractionEntries(groups: MapStackGroup[], orderedLayers: IndexedLayer[], map: MapStackMapInput) {
  const interactions = groupFor(groups, 'interactions');
  const popupLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter((layer) => popupEnabled(layer.popup_config));

  popupLayers.forEach((layer, index) => {
    const drawOrder = GROUP_ORDER_BASE.interactions + index;
    interactions.entries.push({
      id: `interactions:popup:${layer.id}`,
      groupId: 'interactions',
      role: 'interaction-popups',
      title: `${displayLayerName(layer)} popup`,
      subtitle: 'Feature click interaction',
      order: drawOrder,
      orderLabel: `Popup ${index + 1} of ${popupLayers.length}`,
      visible: layer.visible,
      locked: false,
      badges: [
        { label: 'Popup', tone: 'success' },
        ...(layer.visible ? [] : [{ label: 'Hidden layer', tone: 'muted' } as const]),
      ],
      metadata: {
        ...layerMetadata(layer, drawOrder),
        popupEnabled: true,
      },
    });
  });

  const widgets = map.widgets ?? [];
  if (widgets.length > 0) {
    const drawOrder = GROUP_ORDER_BASE.interactions + 500;
    interactions.entries.push({
      id: 'interactions:widgets',
      groupId: 'interactions',
      role: 'interaction-widgets',
      title: 'Map widgets',
      subtitle: widgets.join(', '),
      order: drawOrder,
      orderLabel: 'Widgets',
      visible: true,
      locked: false,
      badges: [{ label: `${widgets.length} widget${widgets.length === 1 ? '' : 's'}`, tone: 'info' }],
      metadata: {
        drawOrder,
        source: 'derived',
        widgets,
      },
    });
  }
}

export function buildMapStack(map: MapStackMapInput): MapStackGroup[] {
  const groups = createEmptyGroups();
  const orderedLayers = sortLayers(map.layers ?? []);
  const duplicates = duplicateIndex(orderedLayers);

  makeSurfaceEntries(groups, orderedLayers, map.terrain_config ?? null);
  makeReliefEntries(groups, orderedLayers, duplicates);
  makeBasemapEntries(groups, map);
  makeDataEntries(groups, orderedLayers, duplicates);
  makeLabelEntries(groups, orderedLayers, map, duplicates);
  makeInteractionEntries(groups, orderedLayers, map);

  return groups;
}

export function flattenMapStack(groups: MapStackGroup[]): MapStackEntry[] {
  return groups.flatMap((group) => group.entries);
}
