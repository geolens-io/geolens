/**
 * fix(#438): I18N-04 — `buildMapStack` is TEST-ONLY: a verification oracle for the saved-map normalizer
 * (`api/__tests__/maps.normalize.test.ts`, `__tests__/map-stack.test.ts`).
 * No production component calls it, so Vite tree-shakes the derived group and
 * entry labels. The shared duplicate helpers below are production code and use
 * `mapStack.badges.copy` for the live stack-row badge.
 *
 * fix(#451): the REST of this module is production code — the shared terrain
 * resolver (`resolveTerrainSourceLayer`, `isTerrainCapableDemLayer`) and
 * helpers are imported by ViewerMap, MapBuilderPage, use-viewer-terrain,
 * terrain-legend, and UnifiedStackPanel. Only `buildMapStack` is test-only.
 */
import type {
  LabelConfig,
  MapBasemapConfig,
  MapLayerResponse,
  MapTerrainConfig,
  PopupConfig,
  StyleConfig,
} from '@/types/api';
import { normalizeBasemapConfig } from '@/lib/basemap-utils';
import i18n from '@/i18n/i18n';
import { getClusterSourceStrategy, isClusterRenderMode, type ClusterSourceStrategyKind, type ClusterSourceStatus } from './cluster-source';

type BuilderTranslator = (key: string, options?: Record<string, unknown>) => string;

const defaultBuilderTranslator: BuilderTranslator = (key, options) =>
  i18n.t(key, { ns: 'builder', ...options }) as string;

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
  | 'basemap-preset'
  | 'basemap-labels'
  | 'data-layer'
  | 'data-labels'
  | 'interaction-popups'
  | 'interaction-plugins';

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
  clusterSource?: {
    kind: ClusterSourceStrategyKind;
    status: ClusterSourceStatus;
  } | null;
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
  plugins?: string[];
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
  basemap_label?: string | null;
  show_basemap_labels?: boolean | null;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  layers?: MapLayerResponse[];
  plugins?: string[] | null;
}

interface IndexedLayer {
  layer: MapLayerResponse;
  originalIndex: number;
}

interface LayerDuplicateIndex {
  byLayerId: Map<string, MapStackDuplicateMetadata>;
}

const GROUP_TITLES: Record<MapStackGroupId, { titleKey: string; descriptionKey: string }> = {
  surface: {
    titleKey: 'mapStack.groups.surface.title',
    descriptionKey: 'mapStack.groups.surface.description',
  },
  relief: {
    titleKey: 'mapStack.groups.relief.title',
    descriptionKey: 'mapStack.groups.relief.description',
  },
  basemap: {
    titleKey: 'mapStack.groups.basemap.title',
    descriptionKey: 'mapStack.groups.basemap.description',
  },
  data: {
    titleKey: 'mapStack.groups.data.title',
    descriptionKey: 'mapStack.groups.data.description',
  },
  labels: {
    titleKey: 'mapStack.groups.labels.title',
    descriptionKey: 'mapStack.groups.labels.description',
  },
  interactions: {
    titleKey: 'mapStack.groups.interactions.title',
    descriptionKey: 'mapStack.groups.interactions.description',
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
    title: defaultBuilderTranslator(GROUP_TITLES[id].titleKey),
    description: defaultBuilderTranslator(GROUP_TITLES[id].descriptionKey),
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
  return layer.display_name
    || layer.dataset_name
    || layer.dataset_table_name
    || defaultBuilderTranslator('mapStack.entries.untitledLayer');
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

// Exported (999.17 MD-01/MD-02): the canonical "is this layer resolvable as a 3D
// terrain source?" predicate. Both the legend synthetic-entry derivation
// (terrain-legend.ts) and the delete-time terrain-clear check
// (builder-layer-mutations.ts) consume THIS one predicate so legend <-> stack
// <-> mesh-resolver stay in lockstep (the phase invariant).
export function isTerrainCapableDemLayer(layer: {
  is_dem?: boolean | null;
  dataset_record_type?: string | null;
}) {
  return layer.is_dem === true && DEM_RECORD_TYPES.has(String(layer.dataset_record_type ?? ''));
}

/**
 * Resolve the DEM layer that backs `terrain_config`, the SINGLE way both the map
 * renderer (BuilderMap) and the settings status
 * (MapBuilderPage `isTerrainActive`) must agree on: match the source dataset and
 * be terrain-capable, regardless of render_mode (a hillshade-mode DEM drives the
 * 3D mesh too). Sharing this prevents the two from drifting — which is exactly
 * what made the settings report "No terrain layer is active" while the map was
 * rendering terrain from a hillshade DEM.
 */
export function resolveTerrainSourceLayer<
  T extends {
    dataset_id?: string | null;
    is_dem?: boolean | null;
    dataset_record_type?: string | null;
    visible?: boolean | null;
  },
>(
  layers: readonly T[],
  terrainConfig: { source_dataset_id?: string | null } | null | undefined,
): T | undefined {
  const src = terrainConfig?.source_dataset_id;
  if (!src) return undefined;
  // fix(HT-10): terrain_config binds a DATASET, but a dataset may have several
  // renderings. Deterministic duplicate semantics: prefer the first visible
  // matching DEM (a hidden rendering detaches builder terrain, so a visible
  // sibling should win), then fall back to the first match in stack order.
  const matches = layers.filter((l) => l.dataset_id === src && isTerrainCapableDemLayer(l));
  return matches.find((l) => l.visible !== false) ?? matches[0];
}

function isTerrainRenderLayer(layer: MapLayerResponse) {
  return isTerrainCapableDemLayer(layer) && renderMode(layer.style_config) === 'terrain';
}

function isDemVisualLayer(layer: MapLayerResponse) {
  return layer.is_dem === true && renderMode(layer.style_config) !== 'terrain';
}

function reliefRole(layer: MapLayerResponse): Extract<MapStackRole, `relief-${string}`> {
  const mode = renderMode(layer.style_config);
  if (mode === 'hillshade') return 'relief-hillshade';
  return 'relief-color';
}

function typeBadge(layer: MapLayerResponse): MapStackBadge {
  const mode = renderMode(layer.style_config);
  if (mode === 'hillshade') return { label: defaultBuilderTranslator('mapStack.badges.hillshade'), tone: 'info' };
  if (mode === 'heatmap') return { label: defaultBuilderTranslator('mapStack.badges.heatmap'), tone: 'info' };
  if (mode === 'cluster') return { label: defaultBuilderTranslator('mapStack.badges.cluster'), tone: 'info' };
  if (mode === 'symbol') return { label: defaultBuilderTranslator('mapStack.badges.symbol'), tone: 'info' };
  if (mode === 'arrow') return { label: defaultBuilderTranslator('mapStack.badges.arrow'), tone: 'info' };
  if (layer.is_dem) return { label: defaultBuilderTranslator('mapStack.badges.dem'), tone: 'info' };
  if (layer.layer_type !== 'raster_geolens' && !layer.dataset_geometry_type) {
    return { label: defaultBuilderTranslator('mapStack.badges.unsupported'), tone: 'warning' };
  }
  if (layer.dataset_geometry_type) return { label: layer.dataset_geometry_type, tone: 'neutral' };
  if (layer.layer_type === 'raster_geolens') return { label: defaultBuilderTranslator('mapStack.badges.raster'), tone: 'neutral' };
  return { label: defaultBuilderTranslator('mapStack.badges.layer'), tone: 'neutral' };
}

function clusterSourceBadge(layer: MapLayerResponse): MapStackBadge | null {
  if (!isClusterRenderMode(layer)) return null;
  const strategy = getClusterSourceStrategy(layer);
  if (strategy.kind === 'server-tile') return { label: defaultBuilderTranslator('mapStack.badges.serverCluster'), tone: 'info' };
  if (strategy.kind === 'bounded-geojson') return { label: defaultBuilderTranslator('mapStack.badges.boundedCluster'), tone: 'success' };
  return { label: defaultBuilderTranslator('mapStack.badges.pointFallback'), tone: 'warning' };
}

function layerBadges(layer: MapLayerResponse, duplicate?: MapStackDuplicateMetadata): MapStackBadge[] {
  const badges = [typeBadge(layer)];
  const sourceBadge = clusterSourceBadge(layer);
  if (sourceBadge) badges.push(sourceBadge);
  if (!layer.visible) badges.push({ label: defaultBuilderTranslator('mapStack.badges.hidden'), tone: 'muted' });
  if (layer.show_in_legend === false) badges.push({ label: defaultBuilderTranslator('mapStack.badges.legendHidden'), tone: 'muted' });
  if (labelColumn(layer.label_config)) badges.push({ label: defaultBuilderTranslator('mapStack.badges.labels'), tone: 'success' });
  if (popupEnabled(layer.popup_config)) badges.push({ label: defaultBuilderTranslator('mapStack.badges.popup'), tone: 'success' });
  if (duplicate?.disambiguationLabel) {
    badges.push({ label: duplicate.disambiguationLabel, tone: 'warning' });
  }
  return badges;
}

function dataOrderLabel(indexFromTop: number, total: number) {
  const position = indexFromTop + 1;
  if (position === 1 && total > 1) return defaultBuilderTranslator('mapStack.order.dataTop', { position, total });
  if (position === total && total > 1) return defaultBuilderTranslator('mapStack.order.dataBottom', { position, total });
  return defaultBuilderTranslator('mapStack.order.data', { position, total });
}

function reliefOrderLabel(indexFromBottom: number, total: number) {
  const position = indexFromBottom + 1;
  if (position === 1 && total > 1) return defaultBuilderTranslator('mapStack.order.reliefBottom', { position, total });
  if (position === total && total > 1) return defaultBuilderTranslator('mapStack.order.reliefTop', { position, total });
  return defaultBuilderTranslator('mapStack.order.relief', { position, total });
}

function dataLabelOrderLabel(indexFromBottom: number, total: number) {
  const position = indexFromBottom + 1;
  if (position === total && total > 1) return defaultBuilderTranslator('mapStack.order.dataLabelsTop', { position, total });
  return defaultBuilderTranslator('mapStack.order.dataLabels', { position, total });
}

function stableDatasetKey(layer: MapLayerResponse) {
  return layer.dataset_id || layer.dataset_table_name || layer.id;
}

/**
 * Compute per-layer-id duplicate disambiguation metadata over an ordered set of
 * layers. This is the single source of truth for the "Copy N of M" label —
 * `duplicateIndex` (legend / derived-stack path) and the live `UnifiedStackPanel`
 * stack-row path both consume it so the two never drift.
 *
 * Output is intentionally identical to the previous inline `duplicateIndex` body;
 * `map-stack.test.ts` guards that contract.
 */
export function computeDisambiguationMetadata(
  layers: MapLayerResponse[],
  t: BuilderTranslator = defaultBuilderTranslator,
): Map<string, MapStackDuplicateMetadata> {
  const datasetCounts = new Map<string, number>();
  const nameCounts = new Map<string, number>();
  for (const layer of layers) {
    const datasetKey = stableDatasetKey(layer);
    const name = displayLayerName(layer);
    datasetCounts.set(datasetKey, (datasetCounts.get(datasetKey) ?? 0) + 1);
    nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1);
  }

  const datasetOccurrences = new Map<string, number>();
  const nameOccurrences = new Map<string, number>();
  const byLayerId = new Map<string, MapStackDuplicateMetadata>();

  for (const layer of layers) {
    const datasetKey = stableDatasetKey(layer);
    const name = displayLayerName(layer);
    const datasetOccurrence = (datasetOccurrences.get(datasetKey) ?? 0) + 1;
    const nameOccurrence = (nameOccurrences.get(name) ?? 0) + 1;
    datasetOccurrences.set(datasetKey, datasetOccurrence);
    nameOccurrences.set(name, nameOccurrence);

    const datasetCount = datasetCounts.get(datasetKey) ?? 1;
    const nameCount = nameCounts.get(name) ?? 1;
    // Disambiguate on NAME collisions only. The badge answers "which of these
    // identical-looking rows is which?" — only ambiguous when the names match.
    // Two differently-named layers off one dataset (e.g. a line + its casing)
    // are an intentional cartographic pair, not a duplicate; badging them on
    // shared dataset_id was pure noise. datasetCount/-Occurrence remain in the
    // metadata for informational consumers.
    byLayerId.set(layer.id, {
      datasetKey,
      datasetOccurrence,
      datasetCount,
      nameOccurrence,
      nameCount,
      disambiguationLabel: nameCount > 1
        ? t('mapStack.badges.copy', { index: nameOccurrence, count: nameCount })
        : null,
    });
  }

  return byLayerId;
}

/**
 * Convenience helper for UI consumers that only need the display label per layer.
 * Returns `Map<layerId, 'Copy N of M' | null>` over the supplied (already
 * order-stable) layer list. Shares `computeDisambiguationMetadata` so the live
 * stack badge and the legend/derived-stack badge always agree.
 */
export function computeDisambiguationLabels(
  layers: MapLayerResponse[],
  t: BuilderTranslator = defaultBuilderTranslator,
): Map<string, string | null> {
  const metadata = computeDisambiguationMetadata(layers, t);
  const labels = new Map<string, string | null>();
  for (const [layerId, meta] of metadata) {
    labels.set(layerId, meta.disambiguationLabel);
  }
  return labels;
}

/**
 * fix(#430 V-17): whether a layer would be silently filtered out for the map's
 * audience. Adding a private dataset to a public/shared map used to succeed
 * with no indication that anonymous/other-audience viewers would never see
 * the layer (the backend's `filter_layer_rows_by_dataset_visibility` drops it
 * server-side). A private map has no audience beyond the owner/grantees, so
 * it is never flagged here — only public/internal (shared) maps can strand a
 * layer this way.
 *
 * Conservative by design: when the dataset_visibility/dataset_status fields
 * are both absent (e.g. an older cached response), this returns `false`
 * rather than guessing — matching the pre-fix behavior of showing no warning,
 * not a false positive on every layer.
 */
export function isLayerHiddenFromMapAudience(
  layer: Pick<MapLayerResponse, 'dataset_visibility' | 'dataset_status'>,
  mapVisibility: 'private' | 'internal' | 'public',
): boolean {
  if (mapVisibility === 'private') return false;
  if (layer.dataset_visibility == null && layer.dataset_status == null) return false;
  return layer.dataset_visibility !== 'public' || layer.dataset_status !== 'published';
}

function duplicateIndex(orderedLayers: IndexedLayer[]): LayerDuplicateIndex {
  const byLayerId = computeDisambiguationMetadata(orderedLayers.map(({ layer }) => layer));
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
    clusterSource: isClusterRenderMode(layer)
      ? {
          kind: getClusterSourceStrategy(layer).kind,
          status: getClusterSourceStrategy(layer).status,
        }
      : null,
    layerVisible: layer.visible,
    legendVisible: layer.show_in_legend !== false,
    labelColumn: labelColumn(layer.label_config),
    popupEnabled: popupEnabled(layer.popup_config),
    duplicate,
  };
}

function makeSurfaceEntries(groups: MapStackGroup[]) {
  const surface = groupFor(groups, 'surface');
  surface.entries.push({
    id: 'surface:background',
    groupId: 'surface',
    role: 'surface-background',
    title: defaultBuilderTranslator('mapStack.entries.baseBackground'),
    subtitle: defaultBuilderTranslator('mapStack.subtitles.surfaceBackground'),
    order: GROUP_ORDER_BASE.surface,
    orderLabel: defaultBuilderTranslator('mapStack.order.surfaceFoundation'),
    visible: true,
    locked: true,
    badges: [{ label: defaultBuilderTranslator('mapStack.badges.background'), tone: 'neutral' }],
    metadata: {
      drawOrder: GROUP_ORDER_BASE.surface,
      source: 'derived',
    },
  });
}

function makeTerrainReliefEntry(
  groups: MapStackGroup[],
  orderedLayers: IndexedLayer[],
  terrainConfig: MapTerrainConfig | null,
) {
  const demLayers = orderedLayers
    .map(({ layer }) => layer)
    .filter(isTerrainCapableDemLayer);
  const terrainLayers = demLayers.filter(isTerrainRenderLayer);
  if (demLayers.length === 0 && !terrainConfig?.source_dataset_id) return;

  const configuredSourceId = terrainConfig?.source_dataset_id ?? null;
  // fix(HT-10): resolve the bound DEM the SAME way BuilderMap does (prefer a
  // visible rendering) so a duplicate can't flip the reported status.
  const selectedDemLayer = configuredSourceId
    ? resolveTerrainSourceLayer(demLayers, terrainConfig) ?? null
    : demLayers[0] ?? null;
  const fallbackLayer = !selectedDemLayer && terrainLayers.length > 0 ? terrainLayers[0] : null;
  const sourceLayer = selectedDemLayer ?? fallbackLayer;
  // fix(HT-01): 'active' matches the runtime resolver (resolveTerrainSourceLayer /
  // BuilderMap): any dataset-matched terrain-capable DEM powers the mesh,
  // regardless of render_mode. The old rule required render_mode === 'terrain'
  // and reported the hybrid hillshade+terrain state as 'disabled' while the map
  // was actively rendering terrain from it.
  // codex(#451): BuilderMap sets no mesh when the bound DEM is hidden
  // (effectiveTerrainEnabled = enabled && demLayerVisible), and Settings gates
  // isTerrainActive the same way — so a hidden source is 'disabled', not
  // 'active', or the stack badge drifts from the map and Settings.
  const sourceVisible = selectedDemLayer ? selectedDemLayer.visible !== false : false;
  const sourceStatus: MapStackTerrainSourceStatus = terrainConfig?.enabled
    ? selectedDemLayer
      ? sourceVisible
        ? 'active'
        : 'disabled'
      : fallbackLayer
        ? 'fallback'
        : 'missing'
    : configuredSourceId
      ? selectedDemLayer
        ? 'disabled'
        : 'missing'
      : terrainLayers.length > 0
        ? 'available'
        : 'disabled';
  const enabled = terrainConfig?.enabled === true && sourceStatus === 'active';
  const title = sourceLayer
    ? displayLayerName(sourceLayer)
    : defaultBuilderTranslator('mapStack.entries.terrainMissing');
  const subtitle = sourceLayer
    ? enabled
      ? defaultBuilderTranslator('mapStack.subtitles.elevationSourceExaggeration', {
          exaggeration: terrainConfig?.exaggeration ?? 1,
        })
      : defaultBuilderTranslator('mapStack.subtitles.elevationSource')
    : configuredSourceId
      ? defaultBuilderTranslator('mapStack.subtitles.savedSourceUnavailable', { id: configuredSourceId })
      : defaultBuilderTranslator('mapStack.subtitles.noDemSource');

  const relief = groupFor(groups, 'relief');
  relief.entries.push({
    id: 'relief:terrain',
    groupId: 'relief',
    role: 'surface-terrain',
    title,
    subtitle,
    order: GROUP_ORDER_BASE.relief - 100,
    orderLabel: defaultBuilderTranslator('mapStack.order.reliefTerrain'),
    visible: enabled,
    locked: false,
    badges: [
      { label: defaultBuilderTranslator('mapStack.badges.terrain'), tone: enabled ? 'success' : 'muted' },
      ...(sourceStatus === 'fallback'
        ? [{ label: defaultBuilderTranslator('mapStack.badges.fallbackSource'), tone: 'warning' } as const]
        : []),
      ...(sourceStatus === 'missing'
        ? [{ label: defaultBuilderTranslator('mapStack.badges.missingSource'), tone: 'warning' } as const]
        : []),
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
  terrainConfig: MapTerrainConfig | null,
) {
  makeTerrainReliefEntry(groups, orderedLayers, terrainConfig);

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
  const label = map.basemap_label?.trim() || defaultBuilderTranslator('mapStack.groups.basemap.title');
  const config = normalizeBasemapConfig(map.basemap_config, map.show_basemap_labels ?? true);
  basemap.entries.push({
    id: `basemap:preset:${style}`,
    groupId: 'basemap',
    role: 'basemap-preset',
    title: label,
    subtitle: style,
    order: GROUP_ORDER_BASE.basemap,
    orderLabel: defaultBuilderTranslator('mapStack.order.basemapFoundation'),
    visible: true,
    locked: false,
    badges: [
      { label: style, tone: 'neutral' },
      { label: defaultBuilderTranslator('mapStack.badges.preset'), tone: 'muted' },
      ...(config.land_water_tone !== 'default'
        ? [{
            label: defaultBuilderTranslator(`mapStack.badges.landWaterTone.${config.land_water_tone}`),
            tone: 'info',
          } as const]
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
    .filter((layer) => !isDemVisualLayer(layer) && !isTerrainRenderLayer(layer));
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
    title: defaultBuilderTranslator('mapStack.entries.basemapLabels'),
    subtitle: showBasemapLabels
      ? config.label_mode === 'subtle'
        ? defaultBuilderTranslator('mapStack.subtitles.subtleLabels')
        : defaultBuilderTranslator('mapStack.subtitles.basemapLabelsVisible')
      : defaultBuilderTranslator('mapStack.subtitles.hiddenByMap'),
    order: GROUP_ORDER_BASE.labels,
    orderLabel: defaultBuilderTranslator('mapStack.order.basemapLabels'),
    visible: showBasemapLabels,
    locked: false,
    badges: [
      { label: defaultBuilderTranslator('mapStack.badges.labels'), tone: showBasemapLabels ? 'success' : 'muted' },
      ...(showBasemapLabels
        ? []
        : [{ label: defaultBuilderTranslator('mapStack.badges.hidden'), tone: 'muted' } as const]),
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
    .filter((layer) => !isDemVisualLayer(layer) && !isTerrainRenderLayer(layer) && labelColumn(layer.label_config));
  [...labelLayers].reverse().forEach((layer, indexFromBottom) => {
    const drawOrder = GROUP_ORDER_BASE.labels + 100 + indexFromBottom;
    const duplicate = duplicates.byLayerId.get(layer.id);
    labels.entries.push({
      id: `labels:data:${layer.id}`,
      groupId: 'labels',
      role: 'data-labels',
      title: defaultBuilderTranslator('mapStack.entries.dataLabels', { name: displayLayerName(layer) }),
      subtitle: defaultBuilderTranslator('mapStack.subtitles.column', { column: labelColumn(layer.label_config) }),
      order: drawOrder,
      orderLabel: dataLabelOrderLabel(indexFromBottom, labelLayers.length),
      visible: layer.visible,
      locked: false,
      badges: [
        { label: defaultBuilderTranslator('mapStack.badges.dataLabels'), tone: 'success' },
        ...(layer.visible
          ? []
          : [{ label: defaultBuilderTranslator('mapStack.badges.hidden'), tone: 'muted' } as const]),
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
    .filter((layer) => !isTerrainRenderLayer(layer) && popupEnabled(layer.popup_config));

  popupLayers.forEach((layer, index) => {
    const drawOrder = GROUP_ORDER_BASE.interactions + index;
    interactions.entries.push({
      id: `interactions:popup:${layer.id}`,
      groupId: 'interactions',
      role: 'interaction-popups',
      title: defaultBuilderTranslator('mapStack.entries.layerPopup', { name: displayLayerName(layer) }),
      subtitle: defaultBuilderTranslator('mapStack.subtitles.featureClick'),
      order: drawOrder,
      orderLabel: defaultBuilderTranslator('mapStack.order.popup', {
        position: index + 1,
        total: popupLayers.length,
      }),
      visible: layer.visible,
      locked: false,
      badges: [
        { label: defaultBuilderTranslator('mapStack.badges.popup'), tone: 'success' },
        ...(layer.visible
          ? []
          : [{ label: defaultBuilderTranslator('mapStack.badges.hiddenLayer'), tone: 'muted' } as const]),
      ],
      metadata: {
        ...layerMetadata(layer, drawOrder),
        popupEnabled: true,
      },
    });
  });

  const plugins = map.plugins ?? [];
  if (plugins.length > 0) {
    const drawOrder = GROUP_ORDER_BASE.interactions + 500;
    interactions.entries.push({
      id: 'interactions:plugins',
      groupId: 'interactions',
      role: 'interaction-plugins',
      title: defaultBuilderTranslator('mapStack.entries.mapPlugins'),
      subtitle: plugins.join(', '),
      order: drawOrder,
      orderLabel: defaultBuilderTranslator('mapStack.order.plugins'),
      visible: true,
      locked: false,
      badges: [{ label: defaultBuilderTranslator('mapStack.badges.plugins', { count: plugins.length }), tone: 'info' }],
      metadata: {
        drawOrder,
        source: 'derived',
        plugins,
      },
    });
  }
}

export function buildMapStack(map: MapStackMapInput): MapStackGroup[] {
  const groups = createEmptyGroups();
  const orderedLayers = sortLayers(map.layers ?? []);
  const duplicates = duplicateIndex(orderedLayers);

  makeSurfaceEntries(groups);
  makeReliefEntries(groups, orderedLayers, duplicates, map.terrain_config ?? null);
  makeBasemapEntries(groups, map);
  makeDataEntries(groups, orderedLayers, duplicates);
  makeLabelEntries(groups, orderedLayers, map, duplicates);
  makeInteractionEntries(groups, orderedLayers, map);

  return groups;
}

export function flattenMapStack(groups: MapStackGroup[]): MapStackEntry[] {
  return groups.flatMap((group) => group.entries);
}
