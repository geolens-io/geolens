import { afterEach, describe, expect, it, vi } from 'vitest';
import { normalizeSavedMap, type NormalizedSavedMap } from '../normalize-saved-map';
import type { MapBasemapConfig, MapLayerResponse, MapResponse, SharedLayerResponse, SharedMapResponse, StyleConfig } from '@/types/api';

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
    dataset_feature_count: overrides.dataset_feature_count ?? null,
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

function makeMapResponse(overrides: Partial<MapResponse> = {}): MapResponse {
  return {
    id: overrides.id ?? 'map-1',
    name: overrides.name ?? 'Test Map',
    description: overrides.description ?? null,
    notes: null,
    center_lng: null,
    center_lat: null,
    zoom: null,
    bearing: 0,
    pitch: 0,
    basemap_style: overrides.basemap_style ?? 'positron',
    show_basemap_labels: overrides.show_basemap_labels ?? true,
    basemap_config: overrides.basemap_config ?? null,
    terrain_config: overrides.terrain_config ?? null,
    visibility: 'private',
    thumbnail_url: null,
    created_by: null,
    created_by_username: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    layers: overrides.layers ?? [],
    layer_count: overrides.layers?.length ?? 0,
    widgets: overrides.widgets ?? null,
    forked_from_id: null,
    forked_from_name: null,
    ...overrides,
  };
}

function makeSharedMapResponse(overrides: Partial<SharedMapResponse> = {}): SharedMapResponse {
  return {
    name: overrides.name ?? 'Shared Map',
    description: overrides.description ?? null,
    center_lng: 0,
    center_lat: 0,
    zoom: 8,
    bearing: 0,
    pitch: 0,
    basemap_style: overrides.basemap_style ?? 'positron',
    // show_basemap_labels intentionally omitted when caller doesn't pass it
    ...(overrides.show_basemap_labels !== undefined
      ? { show_basemap_labels: overrides.show_basemap_labels }
      : {}),
    basemap_config: overrides.basemap_config ?? null,
    terrain_config: overrides.terrain_config ?? null,
    has_non_public_layers: overrides.has_non_public_layers ?? false,
    layers: overrides.layers ?? [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('normalizeSavedMap', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('preserves all six legacy MapResponse fields verbatim', () => {
    const layer = makeMapLayer({ id: 'parcels', dataset_name: 'Parcels' });
    const input = makeMapResponse({
      basemap_style: 'satellite',
      show_basemap_labels: false,
      basemap_config: null,
      terrain_config: null,
      layers: [layer],
      widgets: ['widget-a'],
    });

    const result = normalizeSavedMap(input);

    expect(result.basemap_style).toBe('satellite');
    expect(result.show_basemap_labels).toBe(false);
    expect(result.basemap_config).toBeNull();
    expect(result.terrain_config).toBeNull();
    expect(result.layers).toEqual([layer]);
    expect(result.widgets).toEqual(['widget-a']);
  });

  it('defaults show_basemap_labels to true when omitted on SharedMapResponse', () => {
    // Factory leaves show_basemap_labels absent when not passed
    const input = makeSharedMapResponse({ basemap_style: 'positron', layers: [] });
    // Verify the input truly has no show_basemap_labels
    expect((input as unknown as Record<string, unknown>).show_basemap_labels).toBeUndefined();

    const result = normalizeSavedMap(input);
    expect(result.show_basemap_labels).toBe(true);
  });

  it('preserves show_basemap_labels: false when explicitly set', () => {
    const input = makeSharedMapResponse({ show_basemap_labels: false });
    const result = normalizeSavedMap(input);
    expect(result.show_basemap_labels).toBe(false);
  });

  it('returns layers: [] when input has no layers field', () => {
    const input = {
      basemap_style: 'positron',
      show_basemap_labels: true,
      basemap_config: null,
      terrain_config: null,
      widgets: null,
      // no layers field
    };
    const result = normalizeSavedMap(input);
    expect(result.layers).toEqual([]);
  });

  it('returns widgets: null when input has undefined widgets', () => {
    const input = makeMapResponse({ widgets: undefined });
    const result = normalizeSavedMap(input);
    expect(result.widgets).toBeNull();
  });

  it('preserves terrain_config when source_dataset_id has no matching DEM in layers', () => {
    // d2c5c99c case 2 equivalent — terrain_config carried through verbatim
    const input = makeMapResponse({
      terrain_config: { enabled: true, source_dataset_id: 'missing-dem', exaggeration: 3 },
      layers: [],
    });

    const result = normalizeSavedMap(input);

    expect(result.terrain_config).toEqual({
      enabled: true,
      source_dataset_id: 'missing-dem',
      exaggeration: 3,
    });
    // Normalizer does NOT filter out orphaned terrain configs — consumer handles UX
    expect(result.layers).toEqual([]);
  });

  it('preserves basemap_config: null verbatim', () => {
    // d2c5c99c case 3 equivalent
    const input = makeSharedMapResponse({
      basemap_style: 'positron',
      basemap_config: null,
      terrain_config: null,
      layers: [],
    });
    const result = normalizeSavedMap(input);
    expect(result.basemap_config).toBeNull();
  });

  it('preserves full basemap_config object', () => {
    // d2c5c99c case 4 equivalent — all six config fields flow through
    const config: MapBasemapConfig = {
      label_mode: 'subtle',
      road_visibility: 'hidden',
      boundary_visibility: 'full',
      building_visibility: false,
      land_water_tone: 'muted',
      relief_contrast: 'soft',
    };
    const input = makeMapResponse({ basemap_config: config });
    const result = normalizeSavedMap(input);
    expect(result.basemap_config).toEqual(config);
  });

  it('preserves cluster render_mode style_config on layers', () => {
    // d2c5c99c case 5 equivalent — layers array passed through without per-layer transform
    const bounded = makeMapLayer({
      id: 'bounded-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 250,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });
    const server = makeMapLayer({
      id: 'server-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 25_000,
      sort_order: 1,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });
    const fallback = makeMapLayer({
      id: 'fallback-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: null,
      sort_order: 2,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });

    const input = makeMapResponse({ layers: [bounded, server, fallback] });
    const result = normalizeSavedMap(input);

    expect(result.layers).toHaveLength(3);
    expect(result.layers[0].style_config).toEqual({ render_mode: 'cluster' });
    expect(result.layers[1].style_config).toEqual({ render_mode: 'cluster' });
    expect(result.layers[2].style_config).toEqual({ render_mode: 'cluster' });
    expect(result.layers[0].dataset_feature_count).toBe(250);
    expect(result.layers[1].dataset_feature_count).toBe(25_000);
    expect(result.layers[2].dataset_feature_count).toBeNull();
  });

  it("falls back basemap_style to 'default' and warns in DEV when input.basemap_style is missing", () => {
    // Vitest test runs already have DEV=true; no manual mutation needed.
    // Use vi.stubEnv for reliable env control (import.meta.env is a frozen proxy in some
    // Vitest versions; direct assignment is a no-op and cannot be restored safely).
    vi.stubEnv('DEV', true);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    try {
      const input = {
        show_basemap_labels: true,
        basemap_config: null,
        terrain_config: null,
        layers: [],
        widgets: null,
        // basemap_style deliberately absent
      };
      const result = normalizeSavedMap(input);

      expect(result.basemap_style).toBe('default');
      expect(warnSpy).toHaveBeenCalled();
    } finally {
      warnSpy.mockRestore();
    }
  });

  it("does NOT warn when input.basemap_style is missing outside DEV mode", () => {
    vi.stubEnv('DEV', false);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    try {
      const input = {
        show_basemap_labels: true,
        basemap_config: null,
        terrain_config: null,
        layers: [],
        widgets: null,
        // basemap_style deliberately absent
      };
      const result = normalizeSavedMap(input);

      expect(result.basemap_style).toBe('default');
      expect(warnSpy).not.toHaveBeenCalled();
    } finally {
      warnSpy.mockRestore();
    }
  });

  it('returns a fresh object — does not mutate input', () => {
    const layer = makeMapLayer({ id: 'immutable-layer' });
    const input = makeMapResponse({
      basemap_style: 'positron',
      layers: [layer],
      widgets: ['w1'],
    });
    const inputCopy = JSON.parse(JSON.stringify(input)) as typeof input;

    const result = normalizeSavedMap(input);

    // Result is a different object
    expect(result).not.toBe(input);
    // Input is unchanged
    expect(input.basemap_style).toBe(inputCopy.basemap_style);
    expect(input.layers).toHaveLength(inputCopy.layers.length);
    expect(input.widgets).toEqual(inputCopy.widgets);
  });

  it('carries SharedLayerResponse[] through unchanged when input is SharedMapResponse', () => {
    const sharedLayer: SharedLayerResponse = {
      id: 'shared-1',
      dataset_id: 'ds-1',
      dataset_name: 'Shared Dataset',
      display_name: 'My Layer',
      table_name: 'my_table',
      geometry_type: 'POLYGON',
      column_info: null,
      sort_order: 0,
      visible: true,
      opacity: 0.8,
      paint: { 'fill-color': '#ff0000' },
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      show_in_legend: true,
      layer_type: 'vector_geolens',
      tile_url: '/tiles/vector/ds-1/{z}/{x}/{y}',
      feature_count: 100,
    };

    const input: SharedMapResponse = makeSharedMapResponse({ layers: [sharedLayer] });
    const result = normalizeSavedMap<SharedLayerResponse>(input);

    expect(result.layers).toHaveLength(1);
    expect(result.layers[0]).toEqual(sharedLayer);
    // Verify the tile_url (SharedLayerResponse-specific field) survived
    expect((result.layers[0] as SharedLayerResponse).tile_url).toBe('/tiles/vector/ds-1/{z}/{x}/{y}');
  });

  it('carries MapLayerResponse[] through unchanged when input is MapResponse', () => {
    const layer = makeMapLayer({
      id: 'full-layer',
      dataset_name: 'Full Dataset',
      dataset_table_name: 'full_dataset',
      paint: { 'fill-color': '#00ff00' },
      opacity: 0.5,
    });

    const input = makeMapResponse({ layers: [layer] });
    const result = normalizeSavedMap<MapLayerResponse>(input);

    expect(result.layers).toHaveLength(1);
    expect(result.layers[0]).toEqual(layer);
    expect(result.layers[0].dataset_table_name).toBe('full_dataset');
  });

  it('emits basemap_label: null when input has no basemap_label field', () => {
    const input = makeMapResponse({ basemap_style: 'positron' });
    const result = normalizeSavedMap(input);
    expect(result.basemap_label).toBeNull();
  });

  it('returns NormalizedSavedMap type with all required fields present', () => {
    const input = makeMapResponse();
    const result: NormalizedSavedMap<MapLayerResponse> = normalizeSavedMap(input);

    // All required fields exist (TypeScript would error at compile time if missing)
    expect(typeof result.basemap_style).toBe('string');
    expect(result.basemap_label === null || typeof result.basemap_label === 'string').toBe(true);
    expect(typeof result.show_basemap_labels).toBe('boolean');
    expect(result.basemap_config === null || typeof result.basemap_config === 'object').toBe(true);
    expect(result.terrain_config === null || typeof result.terrain_config === 'object').toBe(true);
    expect(Array.isArray(result.layers)).toBe(true);
    expect(result.widgets === null || Array.isArray(result.widgets)).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Phase 1035 — group_meta field tests
  // -------------------------------------------------------------------------

  it('group_meta: preserves valid record when group_meta is present', () => {
    const result = normalizeSavedMap({ group_meta: { 'g1': { expanded: true } } });
    expect(result.group_meta).toEqual({ 'g1': { expanded: true } });
  });

  it('group_meta: returns empty record when input has no group_meta field', () => {
    const result = normalizeSavedMap({});
    expect(result.group_meta).toEqual({});
  });

  it('group_meta: returns empty record when group_meta is null', () => {
    const result = normalizeSavedMap({ group_meta: null });
    expect(result.group_meta).toEqual({});
  });

  it('group_meta: returns empty record when group_meta is a non-object string', () => {
    // Defensive-parse test: feed a bogus value past the type system.
    const result = normalizeSavedMap({ group_meta: 'not-an-object' } as unknown as Parameters<typeof normalizeSavedMap>[0]);
    expect(result.group_meta).toEqual({});
  });

  it('group_meta: returns empty record when group_meta is an array (rejected by !Array.isArray guard)', () => {
    const result = normalizeSavedMap({ group_meta: [{ expanded: true }] } as unknown as Parameters<typeof normalizeSavedMap>[0]);
    expect(result.group_meta).toEqual({});
  });

  it('group_meta: existing fields still normalize unchanged when group_meta is present', () => {
    const layer = makeMapLayer({ id: 'parcels' });
    const input = makeMapResponse({
      basemap_style: 'satellite',
      show_basemap_labels: false,
      terrain_config: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2 },
      layers: [layer],
      widgets: ['w1'],
    });
    // Attach group_meta via cast
    const inputWithGroupMeta = { ...input, group_meta: { 'g2': { expanded: false } } };
    const result = normalizeSavedMap(inputWithGroupMeta);
    expect(result.basemap_style).toBe('satellite');
    expect(result.show_basemap_labels).toBe(false);
    expect(result.terrain_config).toEqual({ enabled: true, source_dataset_id: 'dem-1', exaggeration: 2 });
    expect(result.layers).toHaveLength(1);
    expect(result.widgets).toEqual(['w1']);
    expect(result.group_meta).toEqual({ 'g2': { expanded: false } });
  });

  it('group_meta: field appears in output for all four input fixture types', () => {
    const legacyMapResponse = makeMapResponse({ layers: [makeMapLayer()] });
    const r1 = normalizeSavedMap({ ...legacyMapResponse, group_meta: { 'ga': { expanded: true } } });
    expect(r1.group_meta).toEqual({ 'ga': { expanded: true } });

    const sharedMapResponse = makeSharedMapResponse({ layers: [] });
    const r2 = normalizeSavedMap({ ...sharedMapResponse, group_meta: { 'gb': { expanded: false } } });
    expect(r2.group_meta).toEqual({ 'gb': { expanded: false } });

    const minimalMap = { basemap_style: 'positron' };
    const r3 = normalizeSavedMap(minimalMap);
    expect(r3.group_meta).toEqual({});

    const emptyMap = {};
    const r4 = normalizeSavedMap(emptyMap);
    expect(r4.group_meta).toEqual({});
  });

  it('builds complete stack from existing saved-map fields (d2c5c99c case 1 equivalent)', () => {
    // d2c5c99c case 1: complete legacy saved-map shape passes through without schema migration
    const parcels = makeMapLayer({
      id: 'parcels',
      dataset_id: 'parcels',
      dataset_name: 'Parcels',
      dataset_geometry_type: 'POLYGON',
      sort_order: 0,
    });

    const input = makeMapResponse({
      basemap_style: 'satellite',
      show_basemap_labels: false,
      terrain_config: null,
      layers: [parcels],
    });

    const result = normalizeSavedMap(input);

    expect(result.basemap_style).toBe('satellite');
    expect(result.show_basemap_labels).toBe(false);
    expect(result.terrain_config).toBeNull();
    expect(result.layers).toHaveLength(1);
    expect(result.layers[0].id).toBe('parcels');
  });
});
