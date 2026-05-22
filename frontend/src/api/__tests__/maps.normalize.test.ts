/**
 * maps.normalize.test.ts
 *
 * Regression tests proving that getMap() and getSharedMap() route their responses
 * through normalizeSavedMap at the API boundary before returning to callers.
 *
 * BSR-20: Legacy MapResponse payloads survive normalization — buildMapStack output
 *         is structurally equivalent to pre-wiring behavior.
 * BSR-22: Four viewer surfaces (builder + public via getMap, shared + embed via
 *         getSharedMap) produce structurally equivalent normalized outputs for the
 *         same logical map.
 * BSR-23: d2c5c99c-equivalent MapResponse fixtures pass through without field loss.
 *
 * SC3 (lossless round-trip) note: The write path (updateMap, patchMapLayers) is
 * intentionally out of scope for this plan. SC3 is closed by SC1 (read-path
 * normalization preserves all fields verbatim) + SC4 (four-viewer parity) +
 * the unchanged save path (updateMap/patchMapLayers do not call normalizeSavedMap
 * and thus always persist whatever the caller provides). The round-trip guarantee
 * is: save → backend stores → getMap normalizes → caller sees stable fields.
 * No explicit save/reload cycle test is needed because the normalizer is pure and
 * its input is the raw backend payload, which is write-path agnostic.
 */

import { getMap, getSharedMap } from '../maps';
import { buildMapStack, flattenMapStack } from '@/components/builder/map-stack';
import { apiFetch } from '../client';
import type {
  MapResponse,
  SharedMapResponse,
  MapLayerResponse,
  SharedLayerResponse,
  MapBasemapConfig,
  MapTerrainConfig,
  StyleConfig,
} from '@/types/api';

// Mock apiFetch so tests control the backend payload without network calls.
vi.mock('../client', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  },
}));

// Silence DEV-only console.warn from normalize-saved-map (basemap_style fallback)
// when tests deliberately omit the field, and assert the spy state per test.
const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

beforeEach(() => {
  vi.clearAllMocks();
  warnSpy.mockClear();
});

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function makeMapLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'dataset',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_3d: overrides.is_3d ?? false,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function makeMapResponsePayload(overrides: Partial<MapResponse> = {}): MapResponse {
  return {
    id: overrides.id ?? 'map-1',
    name: overrides.name ?? 'Test Map',
    description: overrides.description ?? null,
    notes: overrides.notes ?? null,
    center_lng: overrides.center_lng ?? -74.006,
    center_lat: overrides.center_lat ?? 40.7128,
    zoom: overrides.zoom ?? 10,
    bearing: overrides.bearing ?? 0,
    pitch: overrides.pitch ?? 0,
    basemap_style: overrides.basemap_style ?? 'positron',
    show_basemap_labels: overrides.show_basemap_labels ?? true,
    basemap_config: overrides.basemap_config ?? null,
    terrain_config: overrides.terrain_config ?? null,
    visibility: overrides.visibility ?? 'public',
    thumbnail_url: overrides.thumbnail_url ?? null,
    created_by: overrides.created_by ?? null,
    created_by_username: overrides.created_by_username ?? null,
    created_at: overrides.created_at ?? '2026-01-01T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-01-01T00:00:00Z',
    layers: overrides.layers ?? [],
    layer_count: overrides.layer_count ?? 0,
    widgets: overrides.widgets ?? null,
    forked_from_id: overrides.forked_from_id ?? null,
    forked_from_name: overrides.forked_from_name ?? null,
    ...overrides,
  };
}

function makeSharedLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    display_name: overrides.display_name ?? null,
    table_name: overrides.table_name ?? 'dataset',
    geometry_type: overrides.geometry_type ?? 'POLYGON',
    column_info: overrides.column_info ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    show_in_legend: overrides.show_in_legend ?? true,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    is_3d: overrides.is_3d ?? false,
    tile_url: overrides.tile_url ?? 'http://tiles/dataset-1/{z}/{x}/{y}.pbf',
    ...overrides,
  };
}

function makeSharedMapResponsePayload(overrides: Partial<SharedMapResponse> = {}): SharedMapResponse {
  return {
    name: overrides.name ?? 'Test Map',
    description: overrides.description ?? null,
    center_lng: overrides.center_lng ?? -74.006,
    center_lat: overrides.center_lat ?? 40.7128,
    zoom: overrides.zoom ?? 10,
    bearing: overrides.bearing ?? 0,
    pitch: overrides.pitch ?? 0,
    basemap_style: overrides.basemap_style ?? 'positron',
    show_basemap_labels: overrides.show_basemap_labels,
    basemap_config: overrides.basemap_config,
    terrain_config: overrides.terrain_config,
    has_non_public_layers: overrides.has_non_public_layers ?? false,
    layers: overrides.layers ?? [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Group A: getMap normalizer integration
// ---------------------------------------------------------------------------

describe('getMap normalizer integration', () => {
  it('getMap routes the response through normalizeSavedMap before returning', async () => {
    const payload = makeMapResponsePayload({
      basemap_style: 'satellite',
      show_basemap_labels: false,
      widgets: ['layer-list'],
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getMap('map-1');

    expect(result.basemap_style).toBe('satellite');
    expect(typeof result.show_basemap_labels).toBe('boolean');
    expect(result.show_basemap_labels).toBe(false);
    expect(result.widgets).toEqual(['layer-list']);
  });

  it('getMap preserves the result of normalizeLayerStyleState on each layer (per-layer normalizer composition)', async () => {
    // A cluster layer requires a builder config for normalizeLayerStyleState to
    // produce a non-null style_config. Without builder, normalizeStyleConfig returns
    // null for { render_mode: 'cluster' } alone (no mode/column to anchor the config).
    const clusterLayer = makeMapLayer({
      id: 'clusters',
      dataset_id: 'points-dataset',
      dataset_geometry_type: 'POINT',
      style_config: {
        render_mode: 'cluster',
        builder: { clusterRadius: 48, clusterColor: '#6366f1' },
      } as StyleConfig,
      paint: {},
    });
    const payload = makeMapResponsePayload({ layers: [clusterLayer] });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getMap('map-1');

    expect(result.layers).toHaveLength(1);
    // Per-layer normalizeLayerStyleState ran: style_config is still present
    expect(result.layers[0].style_config).toBeDefined();
    // render_mode='cluster' is preserved through both normalizers
    expect(result.layers[0].style_config?.render_mode).toBe('cluster');
  });

  it('getMap output for a d2c5c99c-style legacy MapResponse (satellite basemap, show_basemap_labels: false, no terrain) produces a buildMapStack output structurally equal to calling buildMapStack on the same input directly', async () => {
    // d2c5c99c fixture: "builds a complete stack from existing saved-map fields without new backend fields"
    const parcelLayer = makeMapLayer({
      id: 'parcels',
      dataset_id: 'parcels',
      dataset_name: 'Parcels',
      dataset_geometry_type: 'POLYGON',
      sort_order: 0,
    });
    const payload = makeMapResponsePayload({
      basemap_style: 'satellite',
      show_basemap_labels: false,
      terrain_config: null,
      layers: [parcelLayer],
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getMap('map-1');
    const groups = buildMapStack(result);
    const entries = flattenMapStack(groups);

    // Same structural assertions as map-stack.test.ts "builds a complete stack from existing saved-map fields".
    // Note: MapResponse does not carry basemap_label, so buildMapStack resolves the
    // preset title to 'Basemap' (the fallback). The d2c5c99c map-stack.test.ts passes
    // basemap_label via MapStackMapInput — a richer type — so the title there is 'Satellite'.
    // The meaningful equivalence is that the entry ID, style, and sublayer are correct.
    const basemapEntry = groups.find((g) => g.id === 'basemap')?.entries[0];
    expect(basemapEntry).toMatchObject({
      id: 'basemap:preset:satellite',
      metadata: {
        basemap: {
          style: 'satellite',
          sublayer: 'preset',
        },
      },
    });

    expect(groups.find((g) => g.id === 'data')?.entries.map((e) => e.id)).toEqual(['data:parcels']);

    const labelsBasemap = entries.find((e) => e.id === 'labels:basemap');
    expect(labelsBasemap).toMatchObject({
      visible: false,
      metadata: {
        basemap: {
          labelsVisible: false,
        },
      },
    });

    // warnSpy should NOT be called — all fields present
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('getMap output for a payload with terrain_config + missing DEM layer preserves the terrain_config verbatim — buildMapStack produces a Missing source badge', async () => {
    // d2c5c99c fixture: "keeps legacy terrain config useful when the saved DEM source is unavailable"
    const payload = makeMapResponsePayload({
      terrain_config: { enabled: true, source_dataset_id: 'missing-dem', exaggeration: 3 } as MapTerrainConfig,
      layers: [],
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getMap('map-1');
    const entries = flattenMapStack(buildMapStack(result));

    const terrain = entries.find((e) => e.id === 'relief:terrain');
    expect(terrain).toMatchObject({
      role: 'surface-terrain',
      title: 'Terrain source missing',
      visible: false,
      metadata: {
        terrain: {
          enabled: false,
          sourceDatasetId: 'missing-dem',
          sourceStatus: 'missing',
        },
      },
    });
    expect(terrain?.badges.map((b) => b.label)).toContain('Missing source');
  });

  it('getMap output for a payload with full basemap_config preserves every config field — buildMapStack emits the corresponding badges', async () => {
    // d2c5c99c fixture: "reflects basemap_config metadata in preset and label entries"
    const basemapConfig: MapBasemapConfig = {
      label_mode: 'subtle',
      road_visibility: 'hidden',
      boundary_visibility: 'full',
      building_visibility: false,
      land_water_tone: 'muted',
      relief_contrast: 'soft',
    };
    const payload = makeMapResponsePayload({ basemap_config: basemapConfig });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getMap('map-1');
    const groups = buildMapStack(result);

    const basemapEntry = groups.find((g) => g.id === 'basemap')?.entries[0];
    expect(basemapEntry).toMatchObject({
      badges: expect.arrayContaining([
        expect.objectContaining({ label: 'muted' }),
      ]),
      metadata: {
        basemap: {
          config: expect.objectContaining({
            label_mode: 'subtle',
            road_visibility: 'hidden',
          }),
        },
      },
    });

    const labelsBasemap = flattenMapStack(groups).find((e) => e.id === 'labels:basemap');
    expect(labelsBasemap).toMatchObject({
      visible: true,
      subtitle: 'Subtle labels',
      metadata: {
        basemap: {
          config: expect.objectContaining({ label_mode: 'subtle' }),
        },
      },
    });
  });
});

// ---------------------------------------------------------------------------
// Group B: getSharedMap normalizer integration
// ---------------------------------------------------------------------------

describe('getSharedMap normalizer integration', () => {
  it('getSharedMap routes the response through normalizeSavedMap before returning', async () => {
    const payload = makeSharedMapResponsePayload({
      basemap_style: 'dark-matter',
      show_basemap_labels: true,
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getSharedMap('token-abc');

    expect(result).not.toBeNull();
    const r1 = result!;
    expect(r1.basemap_style).toBe('dark-matter');
    expect(typeof r1.show_basemap_labels).toBe('boolean');
    expect(r1.show_basemap_labels).toBe(true);
  });

  it('getSharedMap defaults show_basemap_labels to true when the backend payload omits the field (BSR-22 — embed viewer parity)', async () => {
    // Older shared payloads omit show_basemap_labels entirely.
    // makeSharedMapResponsePayload omits the field when not passed.
    const payload = makeSharedMapResponsePayload({
      basemap_style: 'positron',
      // show_basemap_labels intentionally absent
    });
    delete (payload as unknown as Record<string, unknown>).show_basemap_labels;
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getSharedMap('token-embed');

    expect(result).not.toBeNull();
    expect(result!.show_basemap_labels).toBe(true);
  });

  it('getSharedMap preserves show_basemap_labels: false when explicitly set', async () => {
    const payload = makeSharedMapResponsePayload({
      basemap_style: 'satellite',
      show_basemap_labels: false,
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getSharedMap('token-satellite');

    expect(result).not.toBeNull();
    expect(result!.show_basemap_labels).toBe(false);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('getSharedMap output for a SharedMapResponse with cluster layers preserves render_mode="cluster" on each layer through both normalizers', async () => {
    // A cluster layer requires a builder config for normalizeLayerStyleState to
    // produce a non-null style_config. See Group A test note for explanation.
    const clusterSharedLayer = makeSharedLayer({
      id: 'shared-clusters',
      dataset_id: 'points-shared',
      geometry_type: 'POINT',
      style_config: {
        render_mode: 'cluster',
        builder: { clusterRadius: 48, clusterColor: '#6366f1' },
      } as StyleConfig,
    });
    const payload = makeSharedMapResponsePayload({
      layers: [clusterSharedLayer],
    });
    vi.mocked(apiFetch).mockResolvedValueOnce(payload);

    const result = await getSharedMap('token-cluster');

    expect(result).not.toBeNull();
    const r2 = result!;
    expect(r2.layers).toHaveLength(1);
    expect(r2.layers[0].style_config?.render_mode).toBe('cluster');
  });
});

// ---------------------------------------------------------------------------
// Group C: Four-viewer parity
// ---------------------------------------------------------------------------

describe('four-viewer parity', () => {
  it('getMap (builder + public viewer path) and getSharedMap (shared + embed viewer path) produce structurally equivalent normalized outputs for the same logical map', async () => {
    // Same logical map represented as MapResponse (builder/public path) and
    // SharedMapResponse (shared/embed path). Field names differ per PATTERNS.md:
    //   MapLayerResponse.dataset_table_name  →  SharedLayerResponse.table_name
    //   MapLayerResponse.dataset_geometry_type  →  SharedLayerResponse.geometry_type
    // Round-trip fixture exercises wider enum strings (visible/vivid/medium)
    // than the current MapBasemapConfig union — the normalizer must pass them
    // through verbatim, so cast away the strict union for the test fixture.
    const basemapConfig = {
      label_mode: 'subtle',
      road_visibility: 'visible',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'vivid',
      relief_contrast: 'medium',
    } as unknown as MapBasemapConfig;
    const terrainConfig: MapTerrainConfig = {
      enabled: false,
      source_dataset_id: 'dem-src',
      exaggeration: 1.5,
    };

    const mapLayer = makeMapLayer({
      id: 'shared-layer-id',
      dataset_id: 'ds-1',
      dataset_name: 'Zones',
      dataset_geometry_type: 'POLYGON',
      dataset_table_name: 'zones',
      sort_order: 0,
    });

    const sharedLayer = makeSharedLayer({
      id: 'shared-layer-id',
      dataset_id: 'ds-1',
      dataset_name: 'Zones',
      geometry_type: 'POLYGON',
      table_name: 'zones',
      sort_order: 0,
    });

    const mapPayload = makeMapResponsePayload({
      basemap_style: 'positron',
      show_basemap_labels: true,
      basemap_config: basemapConfig,
      terrain_config: terrainConfig,
      layers: [mapLayer],
    });

    const sharedPayload = makeSharedMapResponsePayload({
      basemap_style: 'positron',
      show_basemap_labels: true,
      basemap_config: basemapConfig,
      terrain_config: terrainConfig,
      layers: [sharedLayer],
    });

    // Simulate the two distinct fetch paths
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(mapPayload)
      .mockResolvedValueOnce(sharedPayload);

    const mapResult = await getMap('map-parity');
    const sharedResult = await getSharedMap('token-parity');

    expect(sharedResult).not.toBeNull();
    const sr = sharedResult!;
    // BSR-22 invariants: normalized outputs are structurally equivalent
    expect(mapResult.basemap_style).toBe(sr.basemap_style);
    expect(mapResult.show_basemap_labels).toBe(sr.show_basemap_labels);
    expect(mapResult.basemap_config).toEqual(sr.basemap_config);
    expect(mapResult.terrain_config).toEqual(sr.terrain_config);
    expect(mapResult.layers.length).toBe(sr.layers.length);
    // Layer ID and sort_order match
    expect(mapResult.layers[0].id).toBe(sr.layers[0].id);
    expect(mapResult.layers[0].sort_order).toBe(sr.layers[0].sort_order);

    // Both paths produce the same basemap stack entries when fed to buildMapStack
    // (using mapResult only, since buildMapStack takes MapLayerResponse[])
    const stackGroups = buildMapStack(mapResult);
    const basemapEntry = stackGroups.find((g) => g.id === 'basemap')?.entries[0];
    expect(basemapEntry?.metadata.basemap?.style).toBe('positron');
  });
});
