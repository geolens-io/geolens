/**
 * Focused tests for handleAddDataset — BSR-18
 * Tests: sort_order=0, onSuccessCb chain, error handling, backward-compat.
 *
 * Isolated in a separate file to keep the heavy renderHook call for
 * useBuilderLayers out of the main test suite. Heavy transitive deps are
 * mocked here at the module level so the hook can be imported in jsdom.
 */

// ---- module-level mocks for heavy transitive deps ----
// These mocks must be declared BEFORE the hook is imported so vite/vitest
// can hoist them correctly.

vi.mock('react-router', () => {
  // Minimal passthrough stubs so the real react-router bundle (and its heavy
  // transitive deps) are never imported in this isolated test worker.
  // MemoryRouter is needed by test-utils.tsx wrapper; useSearchParams is used
  // by useBuilderLayers.
  const passthrough = (props: Record<string, unknown>) => props['children'] as unknown ?? null;
  return {
    MemoryRouter: passthrough,
    Routes: passthrough,
    Route: () => null,
    Navigate: () => null,
    Outlet: () => null,
    Link: passthrough,
    RouterProvider: passthrough,
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
    useNavigate: () => vi.fn(),
    useLocation: () => ({ pathname: '/', search: '', hash: '', state: null }),
    useParams: () => ({}),
    useMatch: () => null,
    createBrowserRouter: vi.fn(),
    createMemoryRouter: vi.fn(),
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  }),
}));

vi.mock('@/components/builder/hooks/use-ephemeral-layers', () => ({
  useEphemeralLayers: () => ({
    ephemeralResult: null,
    handleQueryResult: vi.fn(),
    handleDismissEphemeral: vi.fn(),
  }),
}));

vi.mock('@/components/builder/hooks/use-layer-map-sync', () => ({
  useLayerMapSync: () => ({
    handleToggleVisibility: vi.fn(),
    handlePaintChange: vi.fn(),
    handleStyleConfigChange: vi.fn(),
    handleOpacityChange: vi.fn(),
    handleLayoutChange: vi.fn(),
    handleFilterChange: vi.fn(),
    handleLabelChange: vi.fn(),
    handlePopupChange: vi.fn(),
  }),
}));

vi.mock('@/components/builder/map-sync', () => ({
  getLayerType: vi.fn(),
  reorderDataLayers: vi.fn(),
}));

vi.mock('@/components/builder/layer-adapters/registry', () => ({
  getAdapter: vi.fn(() => ({ addLayers: vi.fn() })),
}));

vi.mock('@/lib/basemap-utils', () => ({
  resolveBasemapId: (id: string) => id,
}));

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => 'https://example.com/tiles'),
}));

vi.mock('@/components/builder/label-layer-utils', () => ({
  buildLabelLayerSpec: vi.fn(),
}));

vi.mock('@/components/builder/renderAs', () => ({
  buildRenderAsPatch: vi.fn(),
}));

// ---- actual test imports ----

import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    notes: null,
    center_lng: 0,
    center_lat: 0,
    zoom: 2,
    bearing: 0,
    pitch: 0,
    basemap_style: 'positron',
    show_basemap_labels: true,
    basemap_config: null,
    terrain_config: null,
    visibility: 'private',
    thumbnail_url: null,
    created_by: null,
    created_by_username: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    layers,
    layer_count: layers.length,
    forked_from_id: null,
    forked_from_name: null,
  };
}

function renderWithMutation() {
  const mutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];

  const { result } = renderHook(() =>
    useBuilderLayers(
      makeMapData([]),
      { current: null } as React.RefObject<MaplibreMap | null>,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
    ),
  );
  return { result, mutate };
}

describe('handleAddDataset (BSR-18)', () => {
  it('Test A: posts with sort_order: 0 (not layersRef.current.length)', () => {
    const { result, mutate } = renderWithMutation();

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    expect(data).toMatchObject({ dataset_id: 'ds-42', sort_order: 0 });
  });

  it('Test B: invokes onSuccessCb(createdLayer.id) when mutation resolves', () => {
    const { result, mutate } = renderWithMutation();
    const onSuccessCb = vi.fn();

    act(() => {
      result.current.handleAddDataset('ds-42', onSuccessCb);
    });

    // Simulate mutation success with a created layer object
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = { id: 'new-layer-id' };
    act(() => { onSuccess(createdLayer); });

    expect(onSuccessCb).toHaveBeenCalledWith('new-layer-id');
  });

  it('Test C: does NOT call onSuccessCb when mutation errors', () => {
    const { result, mutate } = renderWithMutation();
    const onSuccessCb = vi.fn();

    act(() => {
      result.current.handleAddDataset('ds-42', onSuccessCb);
    });

    const [, { onError }] = mutate.mock.calls[0];
    act(() => { onError(); });

    expect(onSuccessCb).not.toHaveBeenCalled();
  });

  it('Test D: backward-compat — no onSuccessCb arg does not throw', () => {
    const { result, mutate } = renderWithMutation();

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    expect(() => act(() => { onSuccess({ id: 'new-layer-id' }); })).not.toThrow();
  });
});
