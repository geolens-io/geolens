// BUG-042: editing a feature's ATTRIBUTES never reloaded the vector tiles, so
// attribute-driven rendering kept stale values until a manual reload. The
// geometry/delete handlers already reloadTiles(); the attribute handler now
// does too. This test pins that handleEditAttributeSubmit cache-busts the
// vector tile source after a successful update.
import { renderHook, act } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useFeatureEditing } from '@/components/dataset/hooks/use-feature-editing';
import { useDrawingStore } from '@/stores/drawing-store';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn() },
}));

const updateMutateAsync = vi.fn().mockResolvedValue({});
vi.mock('@/hooks/use-features', () => ({
  useCreateFeature: () => ({ mutateAsync: vi.fn() }),
  useUpdateFeature: () => ({ mutateAsync: updateMutateAsync }),
  useDeleteFeature: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: (table: string, _token: unknown, _base: unknown, cacheBust?: string) =>
    `/tiles/${table}/{z}/{x}/{y}.pbf?cb=${cacheBust ?? ''}`,
}));

vi.mock('@/lib/env', () => ({
  getEnvConfig: () => ({ TILE_BASE_URL: '' }),
}));

function makeMapWithVectorSource(setTiles: ReturnType<typeof vi.fn>) {
  return {
    getSource: vi.fn((id: string) =>
      id === 'vector-tile-source' ? { setTiles } : undefined,
    ),
    getLayer: vi.fn(() => undefined),
    setFilter: vi.fn(),
  } as unknown as MaplibreMap;
}

function renderEditing(map: MaplibreMap) {
  const mapRef = { current: map };
  return renderHook(() =>
    useFeatureEditing({
      mapRef,
      datasetId: 'ds-1',
      tableName: 'parcels',
      tileConfig: { cdn_base_url: null },
      tileToken: { sig: 's', exp: 1, scope: 'sc' },
      removeFeatures: vi.fn(),
      getSnapshotFeature: vi.fn(),
      addFeatures: vi.fn(() => []),
      selectFeature: vi.fn(),
      clear: vi.fn(),
    }),
  );
}

describe('useFeatureEditing — handleEditAttributeSubmit (BUG-042)', () => {
  beforeEach(() => {
    updateMutateAsync.mockClear();
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: { name: 'old' } } });
  });

  it('reloads (cache-busts) the vector tiles after a successful attribute update', async () => {
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(updateMutateAsync).toHaveBeenCalledWith({
      datasetId: 'ds-1',
      gid: 7,
      properties: { name: 'new' },
    });
    // The fix: tiles are reloaded via setTiles with a fresh cache-buster.
    expect(setTiles).toHaveBeenCalledTimes(1);
    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=\d+/);
  });

  it('does NOT reload tiles when the attribute update fails', async () => {
    updateMutateAsync.mockRejectedValueOnce(new Error('boom'));
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(setTiles).not.toHaveBeenCalled();
  });
});
