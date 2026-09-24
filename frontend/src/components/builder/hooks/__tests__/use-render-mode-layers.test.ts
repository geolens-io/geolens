/**
 * fix(#392): switching render modes back to point/circle
 * re-adds a layer's companion label layer. That re-add must immediately carry
 * the parent layer's active filter (via the shared `sanitizeNullableNumericFilter`),
 * mirroring the canonical pattern in `use-layer-map-sync.ts`'s label-add path —
 * otherwise filtered-out features briefly render via their labels until the
 * next full sync overwrites them. (audit B-007/LB-02)
 *
 * Mirrors the mock harness in `use-layer-map-sync.test.ts` (vi.mock for
 * layer-adapters/registry, map-sync, maplibre-filter-utils, label-layer-utils,
 * a minimal MaplibreMap stub via vi.fn()).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useRenderModeLayers } from '../use-render-mode-layers';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';
import type { MapLayerResponse } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
const mockAdapter = {
  addLayers: vi.fn(),
  syncVisibility: vi.fn(),
};

vi.mock('@/components/builder/layer-adapters/registry', () => ({
  getAdapter: vi.fn(() => mockAdapter),
}));

vi.mock('@/components/builder/map-sync', async () => ({
  getLayerType: vi.fn(() => 'circle'),
  getSourceIdForLayer: vi.fn((layer: { id: string }) => `source-${layer.id}`),
  toSyncInput: (
    await vi.importActual<typeof import('@/components/builder/map-sync')>('@/components/builder/map-sync')
  ).toSyncInput,
}));

// Identity sanitizer — the exact filter value passed through is asserted below.
vi.mock('@/lib/maplibre-filter-utils', () => ({
  sanitizeNullableNumericFilter: vi.fn((f: unknown) => f),
}));

vi.mock('@/components/builder/label-layer-utils', () => ({
  buildLabelLayerSpec: vi.fn(() => ({ id: 'spec' })),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const LAYER_ID = 'layer-uuid-123';
const ids = getCompanionLayerIds(LAYER_ID);
const LABEL_ID = ids.label;

const makeLayer = (overrides: Partial<MapLayerResponse> = {}): MapLayerResponse => ({
  id: LAYER_ID,
  dataset_id: 'ds-1',
  dataset_name: 'Test',
  dataset_geometry_type: 'Point',
  dataset_table_name: 'test_table',
  dataset_extent_bbox: null,
  dataset_column_info: null,
  dataset_feature_count: null,
  dataset_sample_values: null,
  display_name: 'Test Layer',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: { column: 'name' },
  style_config: null,
  ...overrides,
});

/**
 * Minimal MaplibreMap stub. `getLayer` returns undefined for every id (so the
 * label — and everything else — is treated as absent, driving the fresh
 * point/circle re-add branch), and `getSource` returns a truthy stand-in tile
 * source so the label-add guard (`!map.getLayer(labelId) && map.getSource(sourceId)`)
 * passes.
 */
function makeMapStub() {
  return {
    isStyleLoaded: vi.fn(() => true),
    getLayer: vi.fn(() => undefined),
    getSource: vi.fn(() => ({ tiles: ['https://example.test/tiles/{z}/{x}/{y}'] })),
    addLayer: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
  } as unknown as MaplibreMap;
}

function renderSwap(layer: MapLayerResponse, mapStub: MaplibreMap) {
  const layersRef = { current: [layer] };
  const mapInstanceRef = { current: mapStub };
  const setLocalLayers = vi.fn();
  const setHasUnsavedChanges = vi.fn();

  const { result } = renderHook(() =>
    useRenderModeLayers({
      layersRef,
      setLocalLayers,
      setHasUnsavedChanges,
      mapInstanceRef,
    }),
  );

  return result;
}

describe('useRenderModeLayers — swapLayerOnMap removes a stale label before re-adding (B-007 / LB-02)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('removes an existing label companion before adding the new render mode', () => {
    const layer = makeLayer();
    const mapStub = makeMapStub();
    (mapStub.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => (id === LABEL_ID ? { id } : undefined));
    const result = renderSwap(layer, mapStub);

    act(() => {
      result.current.swapLayerOnMap(layer, 'circle', {});
    });

    // The label is removed unconditionally, like every other companion above
    // it; the new adapter's own addLayers/syncVisibility (asserted elsewhere)
    // re-add it, filter and all, when the new family is labelled.
    expect(mapStub.removeLayer).toHaveBeenCalledWith(LABEL_ID);
    expect(mockAdapter.addLayers).toHaveBeenCalled();
  });

  it('a switch to heatmap drops the label instead of only hiding it (documented change)', () => {
    const layer = makeLayer();
    const mapStub = makeMapStub();
    (mapStub.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => (id === LABEL_ID ? { id } : undefined));
    const result = renderSwap(layer, mapStub);

    act(() => {
      result.current.swapLayerOnMap(layer, 'heatmap', {});
    });

    expect(mapStub.removeLayer).toHaveBeenCalledWith(LABEL_ID);
    expect(mapStub.setLayoutProperty).not.toHaveBeenCalledWith(LABEL_ID, 'visibility', 'none');
  });

  it('heatmap branch does not touch the label filter', () => {
    const filter = ['==', ['get', 'category'], 'A'] as MapLayerResponse['filter'];
    const layer = makeLayer({ filter });
    const mapStub = makeMapStub();
    const result = renderSwap(layer, mapStub);

    act(() => {
      result.current.swapLayerOnMap(layer, 'heatmap', {});
    });

    expect(mapStub.setFilter).not.toHaveBeenCalled();
  });

  it.each(['raster', 'hillshade'] as const)('leaves a %s switch to the sync pass', (adapterType) => {
    const layer = makeLayer({ layer_type: 'raster_geolens', dataset_geometry_type: null, label_config: null });
    const mapStub = makeMapStub();
    const result = renderSwap(layer, mapStub);

    act(() => {
      result.current.swapLayerOnMap(layer, adapterType, {});
    });

    expect(mockAdapter.addLayers).not.toHaveBeenCalled();
    expect(mapStub.removeSource).not.toHaveBeenCalled();
  });

  it('symbol branch does not touch the label filter', () => {
    const filter = ['==', ['get', 'category'], 'A'] as MapLayerResponse['filter'];
    const layer = makeLayer({ filter });
    const mapStub = makeMapStub();
    const result = renderSwap(layer, mapStub);

    act(() => {
      result.current.swapLayerOnMap(layer, 'symbol', {});
    });

    expect(mapStub.setFilter).not.toHaveBeenCalled();
  });
});
