// BUG-042: editing a feature's ATTRIBUTES never reloaded the vector tiles, so
// attribute-driven rendering kept stale values until a manual reload. The
// geometry/delete handlers already reloadTiles(); the attribute handler now
// does too. This test pins that handleEditAttributeSubmit cache-busts the
// vector tile source after a successful update.
import { renderHook, act } from '@testing-library/react';
import type { Map as MaplibreMap, Point } from 'maplibre-gl';
import { toast } from 'sonner';
import { showAllFeaturesInTiles, useFeatureEditing } from '@/components/dataset/hooks/use-feature-editing';
import { previewSourceId, useMapLayers } from '@/components/maps/hooks/use-map-layers';
import { useDrawingStore } from '@/stores/drawing-store';
import { getFeature } from '@/api/features';
import type { GeoJSONFeature } from '@/api/features';
import type { Feature } from 'geojson';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn() },
}));

const createMutateAsync = vi.fn().mockResolvedValue({});
const updateMutateAsync = vi.fn().mockResolvedValue({});
const deleteMutateAsync = vi.fn().mockResolvedValue({});
vi.mock('@/hooks/use-features', () => ({
  useCreateFeature: () => ({ mutateAsync: createMutateAsync }),
  useUpdateFeature: () => ({ mutateAsync: updateMutateAsync }),
  useDeleteFeature: () => ({ mutateAsync: deleteMutateAsync }),
}));

vi.mock('@/lib/tile-utils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/tile-utils')>()),
  buildSignedTileUrl: (table: string, _token: unknown, _base: unknown, cacheBust?: string | number) =>
    `/tiles/${table}/{z}/{x}/{y}.pbf?cb=${cacheBust ?? ''}`,
}));

vi.mock('@/lib/env', () => ({
  getEnvConfig: () => ({ TILE_BASE_URL: '' }),
}));

// fix(#1761 review round 3 P1): selectFeatureFromMap's identity race needs a
// controllable getFeature() promise to hold the function paused mid-await.
vi.mock('@/api/features', () => ({
  getFeature: vi.fn(),
}));

const FAKE_POINT = { x: 0, y: 0 } as unknown as Point;

/** Resolves/rejects on demand, so a test can pause an async call mid-flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeMapWithVectorSource(setTiles: ReturnType<typeof vi.fn>) {
  return {
    getSource: vi.fn((id: string) =>
      id === previewSourceId('parcels') ? { setTiles } : undefined,
    ),
    getLayer: vi.fn(() => undefined),
    setFilter: vi.fn(),
    // saveAndRefresh's success path wires a sourcedata listener regardless
    // of whether a 'drawn-overlay' source is registered on this mock.
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as MaplibreMap;
}

/** A map whose 'drawn-overlay' source is spy-able, and that supports the
 *  on/off event pair saveAndRefresh's tile-load listener needs. */
function makeMapWithOverlaySource(overlaySetData: ReturnType<typeof vi.fn>) {
  return {
    getSource: vi.fn((id: string) =>
      id === 'drawn-overlay' ? { setData: overlaySetData } : undefined,
    ),
    getLayer: vi.fn(() => undefined),
    getFilter: vi.fn(() => null),
    setFilter: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as MaplibreMap;
}

interface EditingOverrides {
  removeFeatures?: (ids: (string | number)[]) => void;
  getSnapshotFeature?: (id: string | number) => Feature | undefined;
  addFeatures?: (features: Feature[]) => { id?: string | number; valid: boolean }[];
  selectFeature?: (id: string) => void;
  clear?: () => void;
  resetHistory?: () => void;
}

function renderEditing(map: MaplibreMap, overrides: EditingOverrides = {}) {
  const mapRef = { current: map };
  const opts = {
    removeFeatures: overrides.removeFeatures ?? vi.fn(),
    getSnapshotFeature: overrides.getSnapshotFeature ?? vi.fn(),
    addFeatures: overrides.addFeatures ?? vi.fn(() => []),
    selectFeature: overrides.selectFeature ?? vi.fn(),
    clear: overrides.clear ?? vi.fn(),
    resetHistory: overrides.resetHistory ?? vi.fn(),
  };
  const hook = renderHook(() =>
    useFeatureEditing({
      mapRef,
      datasetId: 'ds-1',
      tableName: 'parcels',
      tileConfig: { cdn_base_url: null },
      tileToken: { sig: 's', exp: 1, scope: 'sc' },
      ...opts,
    }),
  );
  return { ...hook, opts };
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

// fix(#1761 review round 3 P1): a stale selectFeatureFromMap resolution used
// to install the fetched geometry on the map (clear() + addFeatures()) and
// select/hide it BEFORE anything checked whether the identity that started
// the fetch was still current — only the final setSelectedFeature() call was
// epoch-gated, by which point the map mutations had already happened.
describe('useFeatureEditing — selectFeatureFromMap identity race (fix #1761 review round 3 P1)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    // An active drawing target is a precondition for selectFeatureFromMap
    // in real usage (it only runs while activeMode === 'select'), and
    // matters here so the epoch check below is what refuses the write, not
    // the separate "no active target" guard.
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    vi.mocked(getFeature).mockReset();
  });

  function makeSelectableMap() {
    return {
      getLayer: vi.fn(() => true),
      getFilter: vi.fn(() => null),
      queryRenderedFeatures: vi.fn(() => [{ id: 99, properties: {} }]),
      getSource: vi.fn(() => undefined),
      setFilter: vi.fn(),
    } as unknown as MaplibreMap;
  }

  it('does not mutate the map or select the feature when identity changes while getFeature is pending', async () => {
    const fetch = deferred<GeoJSONFeature>();
    vi.mocked(getFeature).mockReturnValueOnce(fetch.promise);

    const clear = vi.fn();
    const addFeatures = vi.fn(() => [{ id: 'td-x', valid: true }]);
    const selectFeature = vi.fn();
    const map = makeSelectableMap();
    const { result, opts } = renderEditing(map, { clear, addFeatures, selectFeature });

    const selecting = result.current.selectFeatureFromMap(map, FAKE_POINT);

    // Identity changes (the auth choke point's bumpSessionEpoch) WHILE the
    // fetch above is still pending.
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });

    fetch.resolve({
      type: 'Feature',
      id: 99,
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: { secret: 'the-previous-identity-should-never-see-this-applied' },
    });
    await act(async () => {
      await selecting;
    });

    expect(clear).not.toHaveBeenCalled();
    expect(addFeatures).not.toHaveBeenCalled();
    expect(opts.selectFeature).not.toHaveBeenCalled();
    expect(map.setFilter).not.toHaveBeenCalled();
    expect(useDrawingStore.getState().selectedFeature).toBeNull();
  });

  it('still selects the feature normally when the identity has not changed', async () => {
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature',
      id: 99,
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: { name: 'ok' },
    });

    const addFeatures = vi.fn(() => [{ id: 'td-x', valid: true }]);
    const map = makeSelectableMap();
    const { result } = renderEditing(map, { addFeatures });

    await act(async () => {
      await result.current.selectFeatureFromMap(map, FAKE_POINT);
    });

    expect(addFeatures).toHaveBeenCalledTimes(1);
    expect(useDrawingStore.getState().selectedFeature).toEqual({
      gid: 99,
      tdId: 'td-x',
      properties: { name: 'ok' },
    });
  });
});

// fix(#1761 review round 3 P2): handleSaveEdit/handleDeleteFeature applied
// their success cleanup (removeFeatures, tile reload/restore,
// clearSelectedFeature) unconditionally. If the identity changed while the
// mutation was in flight, that cleanup landed on whatever a SECOND identity
// had since selected — removing their terra draw feature by a colliding
// tdId and wiping their selection.
describe('useFeatureEditing — post-mutation cleanup skipped after a stale identity (fix #1761 review round 3 P2)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    updateMutateAsync.mockClear();
    deleteMutateAsync.mockClear();
  });

  it('handleSaveEdit skips cleanup when the identity changed while the update was in flight', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);

    const removeFeatures = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, getSnapshotFeature });

    const saving = result.current.handleSaveEdit();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    update.resolve({});
    await act(async () => {
      await saving;
    });

    expect(removeFeatures).not.toHaveBeenCalled();
    expect(map.setFilter).not.toHaveBeenCalled();
    // clearSelectedFeature was skipped: the (possibly second identity's)
    // selectedFeature is untouched.
    expect(useDrawingStore.getState().selectedFeature).toEqual({ gid: 7, tdId: 'td-7', properties: {} });
  });

  it('handleSaveEdit skips cleanup when another dataset is opened while the update is in flight', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);

    const removeFeatures = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, getSnapshotFeature });

    const saving = result.current.handleSaveEdit();
    act(() => {
      useDrawingStore.getState().setDrawing('ds-2', 'buildings', 'Point');
      useDrawingStore.getState().setSelectedFeature(
        { gid: 7, tdId: 'td-7', properties: { dataset: 'ds-2' } },
        useDrawingStore.getState().sessionEpoch,
      );
    });
    update.resolve({});
    await act(async () => {
      await saving;
    });

    expect(removeFeatures).not.toHaveBeenCalled();
    expect(map.setFilter).not.toHaveBeenCalled();
    expect(useDrawingStore.getState().selectedFeature).toEqual({
      gid: 7,
      tdId: 'td-7',
      properties: { dataset: 'ds-2' },
    });
  });

  it('handleSaveEdit does not clear a newer selection in the same dataset', async () => {
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    useDrawingStore.getState().setSelectedFeature(
      { gid: 7, tdId: 'td-7', properties: {} },
      useDrawingStore.getState().sessionEpoch,
    );
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);

    const removeFeatures = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, getSnapshotFeature });

    const saving = result.current.handleSaveEdit();
    act(() => {
      useDrawingStore.getState().setSelectedFeature(
        { gid: 8, tdId: 'td-8', properties: { name: 'new selection' } },
        useDrawingStore.getState().sessionEpoch,
      );
    });
    update.resolve({});
    await act(async () => {
      await saving;
    });

    expect(removeFeatures).not.toHaveBeenCalled();
    expect(useDrawingStore.getState().selectedFeature).toEqual({
      gid: 8,
      tdId: 'td-8',
      properties: { name: 'new selection' },
    });
  });

  it('handleSaveEdit still cleans up normally when the identity has not changed', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const removeFeatures = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, getSnapshotFeature });

    await act(async () => {
      await result.current.handleSaveEdit();
    });

    expect(removeFeatures).toHaveBeenCalledWith(['td-7']);
    expect(useDrawingStore.getState().selectedFeature).toBeNull();
  });

  it('handleDeleteFeature skips cleanup when the identity changed while the delete was in flight', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const del = deferred<unknown>();
    deleteMutateAsync.mockReturnValueOnce(del.promise);

    const removeFeatures = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures });

    const deleting = result.current.handleDeleteFeature();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    del.resolve({});
    await act(async () => {
      await deleting;
    });

    expect(removeFeatures).not.toHaveBeenCalled();
    expect(map.setFilter).not.toHaveBeenCalled();
    expect(useDrawingStore.getState().selectedFeature).toEqual({ gid: 7, tdId: 'td-7', properties: {} });
  });

  it('handleDeleteFeature still cleans up normally when the identity has not changed', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const removeFeatures = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures });

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(removeFeatures).toHaveBeenCalledWith(['td-7']);
    expect(useDrawingStore.getState().selectedFeature).toBeNull();
  });
});

// fix(round1 #1795): a drag/vertex edit only marks the edit dirty
// (handleEditFinish) — it is not persisted until Save. The undo history for
// that pending edit must survive until it actually settles: a successful
// save, or a cancel/deselection (performDeselect, shared by both).
describe('useFeatureEditing — undo history reset on settle, not on finish (fix round1/round2 #1795)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    updateMutateAsync.mockClear();
    deleteMutateAsync.mockClear();
  });

  it('handleSaveEdit resets the undo history once the update settles normally', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const resetHistory = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { getSnapshotFeature, resetHistory });

    await act(async () => {
      await result.current.handleSaveEdit();
    });

    expect(resetHistory).toHaveBeenCalledTimes(1);
  });

  it('handleSaveEdit does NOT reset the undo history when cleanup is skipped for a stale identity', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);
    const resetHistory = vi.fn();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { getSnapshotFeature, resetHistory });

    const saving = result.current.handleSaveEdit();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    update.resolve({});
    await act(async () => {
      await saving;
    });

    expect(resetHistory).not.toHaveBeenCalled();
  });

  it('performDeselect (also used for Cancel) resets the undo history', () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const resetHistory = vi.fn();
    const removeFeatures = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, resetHistory });

    act(() => {
      result.current.performDeselect();
    });

    expect(resetHistory).toHaveBeenCalledTimes(1);
    expect(useDrawingStore.getState().selectedFeature).toBeNull();
  });

  it('performDeselect is a no-op (including no history reset) when nothing is selected', () => {
    useDrawingStore.setState({ selectedFeature: null });
    const resetHistory = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { resetHistory });

    act(() => {
      result.current.performDeselect();
    });

    expect(resetHistory).not.toHaveBeenCalled();
  });

  // fix(round2 #1795, P2): handleDeleteFeature's success path removed the
  // feature and cleared the selection but never reset the undo history —
  // canUndo stayed true and Undo restored the deleted geometry as a
  // client-side ghost. Reset at the same point handleSaveEdit does, after
  // the stale-epoch check.
  it('handleDeleteFeature resets the undo history once the delete settles normally', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const resetHistory = vi.fn();
    const removeFeatures = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, resetHistory });

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(resetHistory).toHaveBeenCalledTimes(1);
  });

  it('handleDeleteFeature does NOT reset the undo history when cleanup is skipped for a stale identity', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const del = deferred<unknown>();
    deleteMutateAsync.mockReturnValueOnce(del.promise);
    const resetHistory = vi.fn();
    const removeFeatures = vi.fn();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { removeFeatures, resetHistory });

    const deleting = result.current.handleDeleteFeature();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    del.resolve({});
    await act(async () => {
      await deleting;
    });

    expect(resetHistory).not.toHaveBeenCalled();
  });
});

// fix(round2 #1795, P2): Terra Draw's undo() reverts snapshots and updates
// canUndo, but never touched isEditDirty — undoing all the way back to the
// original geometry still triggered the unsaved-changes confirmation on
// Cancel/Done/mode-switch. handleHistoryBaseline is what use-terra-draw's
// onHistoryBaseline callback fires into; a subsequent edit re-dirties
// normally through the existing handleEditFinish.
describe('useFeatureEditing — handleHistoryBaseline clears isEditDirty (fix round2 #1795)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
  });

  it('clears isEditDirty when the undo ring reports it reached baseline', () => {
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    act(() => {
      result.current.handleEditFinish('td-7', {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: {},
      });
    });
    expect(useDrawingStore.getState().isEditDirty).toBe(true);

    act(() => {
      result.current.handleHistoryBaseline();
    });
    expect(useDrawingStore.getState().isEditDirty).toBe(false);
  });

  it('a subsequent edit re-dirties normally after a baseline reset (drag, undo, drag)', () => {
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    act(() => {
      result.current.handleEditFinish('td-7', {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: {},
      });
    });
    act(() => {
      result.current.handleHistoryBaseline();
    });
    expect(useDrawingStore.getState().isEditDirty).toBe(false);

    act(() => {
      result.current.handleEditFinish('td-7', {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
    expect(useDrawingStore.getState().isEditDirty).toBe(true);
  });
});

// fix(round4 #1795, P2): undo() restored a snapshot that no longer contains
// the feature that was selected before the undo — Terra Draw's own select
// state has nothing left to re-select. handleSelectionLost clears our
// selection store too, so it agrees with what Terra Draw actually has.
describe('useFeatureEditing — handleSelectionLost clears the selection store (fix round4 #1795)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
  });

  it('clears selectedFeature (and isEditDirty) when the lost id matches the current selection', () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} }, isEditDirty: true });
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    act(() => {
      result.current.handleSelectionLost('td-7');
    });

    expect(useDrawingStore.getState().selectedFeature).toBeNull();
    expect(useDrawingStore.getState().isEditDirty).toBe(false);
  });

  it('does nothing when the lost id does not match the current selection (a newer selection has since replaced it)', () => {
    useDrawingStore.setState({ selectedFeature: { gid: 9, tdId: 'td-9', properties: {} }, isEditDirty: true });
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    act(() => {
      result.current.handleSelectionLost('td-7');
    });

    expect(useDrawingStore.getState().selectedFeature).toEqual({ gid: 9, tdId: 'td-9', properties: {} });
    expect(useDrawingStore.getState().isEditDirty).toBe(true);
  });

  it('does nothing when nothing is currently selected', () => {
    useDrawingStore.setState({ selectedFeature: null });
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    act(() => {
      result.current.handleSelectionLost('td-7');
    });

    expect(useDrawingStore.getState().selectedFeature).toBeNull();
  });
});

// fix(#1761 review round 4): the epoch-change cleanup (DatasetMap's
// finishDrawingSession) clears Terra Draw but, before this, not the overlay
// ref/source that saveAndRefresh populates for instant visibility while a
// create is in flight — and clearOverlay(), fired later by a tile-load
// event or a 5s fallback, could erase a NEWER identity's own overlay if it
// fired after a second identity change.
describe('useFeatureEditing — overlay reset on identity change (fix #1761 review round 4)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    createMutateAsync.mockClear();
  });

  it('resetOverlay empties the drawn-overlay source and cancels the pending tile-load listener', async () => {
    const overlaySetData = vi.fn();
    const map = makeMapWithOverlaySource(overlaySetData);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });
    // The success path installed a sourcedata listener to clear the
    // overlay once tiles catch up — nothing has canceled it yet.
    expect(map.off).not.toHaveBeenCalled();

    overlaySetData.mockClear();
    act(() => {
      result.current.resetOverlay();
    });

    expect(overlaySetData).toHaveBeenCalledWith({ type: 'FeatureCollection', features: [] });
    expect(map.off).toHaveBeenCalledWith('sourcedata', expect.any(Function));
  });

  it('does not erase a newer overlay when a stale tile-load event fires after a later identity change', async () => {
    const overlaySetData = vi.fn();
    const map = makeMapWithOverlaySource(overlaySetData);
    const { result } = renderEditing(map);

    // User A's create succeeds while their identity is still current — the
    // success path installs the tile-load listener.
    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, { owner: 'A' });
    });
    const onCall = (map.on as ReturnType<typeof vi.fn>).mock.calls.find(([event]) => event === 'sourcedata');
    expect(onCall).toBeDefined();
    const onSourceData = onCall![1] as (e: { sourceId?: string; isSourceLoaded?: boolean }) => void;

    // A second identity draws and saves their OWN overlay feature before
    // A's tile-load event arrives.
    createMutateAsync.mockReturnValueOnce(new Promise(() => {}));
    overlaySetData.mockClear();
    act(() => {
      void result.current.saveAndRefresh({ type: 'Point', coordinates: [1, 1] }, { owner: 'B' });
    });
    expect(overlaySetData).toHaveBeenLastCalledWith({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { owner: 'A' } },
        { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 1] }, properties: { owner: 'B' } },
      ],
    });

    // The identity changes again before A's tile-load event fires.
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });

    // A's stale tile-load event finally arrives.
    overlaySetData.mockClear();
    act(() => {
      onSourceData({ sourceId: previewSourceId('parcels'), isSourceLoaded: true });
    });

    // Refused: B's overlay feature must be untouched.
    expect(overlaySetData).not.toHaveBeenCalled();
  });
});

// fix(#1761 review round 4): handleEditAttributeSubmit used to report
// success and reload tiles even after a stale write, and its caller
// (DatasetMap's AttributeForm onSubmit) closed the dialog unconditionally —
// discarding a second identity's own now-open editor for their feature.
describe('useFeatureEditing — handleEditAttributeSubmit result (fix #1761 review round 4)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    updateMutateAsync.mockClear();
  });

  it('returns applied: false and skips the store write when the identity changed mid-flight', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: { name: 'old' } } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);
    // Mocks are not auto-cleared between tests in this file; earlier tests
    // in this describe legitimately call toast.error for their own (non-
    // stale) failures.
    vi.mocked(toast.error).mockClear();

    const submitting = result.current.handleEditAttributeSubmit({ name: 'new' });
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    update.resolve({});
    let outcome: { applied: boolean } | undefined;
    await act(async () => {
      outcome = await submitting;
    });

    expect(outcome).toEqual({ applied: false });
    // The store write was skipped: the (possibly second identity's)
    // selectedFeature is untouched.
    expect(useDrawingStore.getState().selectedFeature).toEqual({ gid: 7, tdId: 'td-7', properties: { name: 'old' } });
  });

  it('returns applied: true and applies the write when the identity has not changed', async () => {
    // setDrawing establishes an active target — setSelectedFeature (called
    // internally on success) refuses when there is none, per drawing-store's
    // own guard.
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: { name: 'old' } } });
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);

    let outcome: { applied: boolean } | undefined;
    await act(async () => {
      outcome = await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(outcome).toEqual({ applied: true });
    expect(useDrawingStore.getState().selectedFeature).toEqual({ gid: 7, tdId: 'td-7', properties: { name: 'new' } });
  });

  it('returns applied: true and refused: true on a real failure', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    updateMutateAsync.mockRejectedValueOnce(new Error('boom'));
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);

    let outcome: { applied: boolean; refused?: boolean } | undefined;
    await act(async () => {
      outcome = await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(outcome).toEqual({ applied: true, refused: true });
  });

  // fix(#1761 review round 5): the catch path returned applied: true
  // unconditionally, so when the identity changed while the mutation was
  // in flight and it then REJECTED, the caller closed a second identity's
  // own now-open editor and an error toast for the FIRST identity's
  // failure surfaced to whoever is looking now.
  it('returns applied: false and suppresses the error toast when the identity changed before the mutation rejected', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);
    // Mocks are not auto-cleared between tests in this file; earlier tests
    // in this describe legitimately call toast.error for their own (non-
    // stale) failures.
    vi.mocked(toast.error).mockClear();

    const submitting = result.current.handleEditAttributeSubmit({ name: 'new' });
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    update.reject(new Error('boom'));
    let outcome: { applied: boolean } | undefined;
    await act(async () => {
      outcome = await submitting;
    });

    expect(outcome).toEqual({ applied: false });
    expect(toast.error).not.toHaveBeenCalled();
  });
});

// fix(#1761 review round 7): the success path of each mutation already
// rechecks the captured epoch before its toast/state effects; the catch
// path did not, so a request that FAILED after an identity change still
// surfaced its error toast to whoever is signed in now.
describe('useFeatureEditing — stale-failure feedback suppressed (fix #1761 review round 7)', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    createMutateAsync.mockClear();
    updateMutateAsync.mockClear();
    deleteMutateAsync.mockClear();
    // Mocks are not auto-cleared between tests in this file; earlier
    // describes legitimately call toast.error for their own (non-stale)
    // failures.
    vi.mocked(toast.error).mockClear();
  });

  it('saveAndRefresh (create) suppresses the error toast when the identity changed before the request rejected', async () => {
    const overlaySetData = vi.fn();
    const map = makeMapWithOverlaySource(overlaySetData);
    const { result } = renderEditing(map);

    const create = deferred<unknown>();
    createMutateAsync.mockReturnValueOnce(create.promise);

    const saving = result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    create.reject(new Error('boom'));
    let outcome: { saved: boolean; refused?: boolean } | undefined;
    await act(async () => {
      outcome = await saving;
    });

    expect(toast.error).not.toHaveBeenCalled();
    expect(outcome).toEqual({ saved: false });
  });

  it('saveAndRefresh (create) still reports a real failure when the identity has not changed', async () => {
    const overlaySetData = vi.fn();
    const map = makeMapWithOverlaySource(overlaySetData);
    const { result } = renderEditing(map);

    createMutateAsync.mockRejectedValueOnce(new Error('boom'));

    let outcome: { saved: boolean; refused?: boolean } | undefined;
    await act(async () => {
      outcome = await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });

    expect(outcome).toEqual({ saved: false, refused: true });
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it('handleSaveEdit (geometry update) suppresses the error toast when the identity changed before the request rejected', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const update = deferred<unknown>();
    updateMutateAsync.mockReturnValueOnce(update.promise);

    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { getSnapshotFeature });

    const saving = result.current.handleSaveEdit();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    update.reject(new Error('boom'));
    await act(async () => {
      await saving;
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('handleSaveEdit (geometry update) still reports a real failure when the identity has not changed', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    updateMutateAsync.mockRejectedValueOnce(new Error('boom'));
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { getSnapshotFeature });

    await act(async () => {
      await result.current.handleSaveEdit();
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it('handleDeleteFeature (delete) suppresses the error toast when the identity changed before the request rejected', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    const del = deferred<unknown>();
    deleteMutateAsync.mockReturnValueOnce(del.promise);

    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    const deleting = result.current.handleDeleteFeature();
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    del.reject(new Error('boom'));
    await act(async () => {
      await deleting;
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('handleDeleteFeature (delete) still reports a real failure when the identity has not changed', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    deleteMutateAsync.mockRejectedValueOnce(new Error('boom'));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  // fix(#1761 review round 8): the fourth catch path with the same
  // omission — selectFeatureFromMap's catch (getFeature() rejecting) had
  // no epoch recheck at all, unlike the mutation catch paths above, so a
  // failed fetch always showed map.featureLoadFailed to whoever is signed
  // in (or anonymous) when it lands, not whoever clicked the feature.
  it('selectFeatureFromMap (selection) suppresses the error toast when the identity changed before getFeature rejected', async () => {
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    vi.mocked(getFeature).mockReset();
    const fetch = deferred<GeoJSONFeature>();
    vi.mocked(getFeature).mockReturnValueOnce(fetch.promise);

    const map = {
      getLayer: vi.fn(() => true),
      getFilter: vi.fn(() => null),
      queryRenderedFeatures: vi.fn(() => [{ id: 99, properties: {} }]),
      getSource: vi.fn(() => undefined),
      setFilter: vi.fn(),
    } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    const selecting = result.current.selectFeatureFromMap(map, FAKE_POINT);
    act(() => {
      useDrawingStore.getState().bumpSessionEpoch();
    });
    fetch.reject(new Error('boom'));
    await act(async () => {
      await selecting;
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('selectFeatureFromMap (selection) still reports a real failure when the identity has not changed', async () => {
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    vi.mocked(getFeature).mockReset();
    vi.mocked(getFeature).mockRejectedValueOnce(new Error('boom'));

    const map = {
      getLayer: vi.fn(() => true),
      getFilter: vi.fn(() => null),
      queryRenderedFeatures: vi.fn(() => [{ id: 99, properties: {} }]),
      getSource: vi.fn(() => undefined),
      setFilter: vi.fn(),
    } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.selectFeatureFromMap(map, FAKE_POINT);
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
  });
});


describe('drawing session return to the same dataset', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
  });

  it('ignores create completion after leaving and reopening the drawing target', async () => {
    const request = deferred<unknown>();
    createMutateAsync.mockReturnValueOnce(request.promise);
    const { result } = renderEditing(makeMapWithVectorSource(vi.fn()));
    let saving!: Promise<{ saved: boolean; refused?: boolean }>;
    act(() => {
      saving = result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });
    act(() => {
      useDrawingStore.getState().setDrawing('ds-2', 'other', 'Point');
      useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    });
    await act(async () => {
      request.resolve({});
      expect(await saving).toEqual({ saved: false });
    });
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('ignores a feature fetch after leaving and reopening the drawing target', async () => {
    const request = deferred<GeoJSONFeature>();
    vi.mocked(getFeature).mockReturnValueOnce(request.promise);
    const map = {
      getLayer: vi.fn(() => true),
      queryRenderedFeatures: vi.fn(() => [{ id: 9, properties: {} }]),
      getSource: vi.fn(),
      setFilter: vi.fn(),
      getFilter: vi.fn(),
    } as unknown as MaplibreMap;
    const { result, opts } = renderEditing(map);
    let selecting!: Promise<void>;
    act(() => { selecting = result.current.selectFeatureFromMap(map, FAKE_POINT); });
    act(() => {
      useDrawingStore.getState().setDrawing('ds-2', 'other', 'Point');
      useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    });
    await act(async () => {
      request.resolve({ type: 'Feature', id: 9, geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} });
      await selecting;
    });
    expect(opts.clear).not.toHaveBeenCalled();
    expect(opts.addFeatures).not.toHaveBeenCalled();
  });
});

// A client-side navigation with nothing dirty (the unsaved guard allows it)
// can leave the store's target pointing at a dataset OTHER than the one a
// mounted map's useFeatureEditing is bound to, with no epoch bump (same
// identity) and no generation change (a fresh hook instance starts at 0) to
// catch it via the staleness checks above. These entry-point guards are the
// last line of defense even if a stale toolbar render slips through.
describe('useFeatureEditing — mutation entry points refuse a session for a different dataset', () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    createMutateAsync.mockClear();
    updateMutateAsync.mockClear();
    deleteMutateAsync.mockClear();
  });

  function adoptOtherDatasetSelection() {
    useDrawingStore.getState().setDrawing('ds-A', 'a_table', 'Point');
    useDrawingStore.getState().setSelectedFeature(
      { gid: 7, tdId: 'td-7', properties: {} },
      useDrawingStore.getState().sessionEpoch,
    );
  }

  it('handleDeleteFeature refuses and ends the session for a different dataset\'s selection', async () => {
    adoptOtherDatasetSelection();
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map); // bound to datasetId: 'ds-1'

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(deleteMutateAsync).not.toHaveBeenCalled();
    expect(useDrawingStore.getState().isDrawing).toBe(false);
    expect(useDrawingStore.getState().targetDatasetId).toBeNull();
  });

  it('handleSaveEdit refuses a geometry update for a different dataset\'s selection', async () => {
    adoptOtherDatasetSelection();
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map, { getSnapshotFeature });

    await act(async () => {
      await result.current.handleSaveEdit();
    });

    expect(updateMutateAsync).not.toHaveBeenCalled();
  });

  it('handleEditAttributeSubmit refuses an attribute save for a different dataset\'s selection', async () => {
    adoptOtherDatasetSelection();
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);

    let outcome: { applied: boolean } | undefined;
    await act(async () => {
      outcome = await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(updateMutateAsync).not.toHaveBeenCalled();
    expect(outcome).toEqual({ applied: true });
  });

  it('handleDeleteFeature still proceeds when the selection belongs to this hook\'s own dataset', async () => {
    useDrawingStore.getState().setDrawing('ds-1', 'parcels', 'Point');
    useDrawingStore.getState().setSelectedFeature(
      { gid: 7, tdId: 'td-7', properties: {} },
      useDrawingStore.getState().sessionEpoch,
    );
    deleteMutateAsync.mockResolvedValueOnce({ tile_cache_version: 1 });
    const map = { getLayer: vi.fn(() => true), getFilter: vi.fn(() => null), setFilter: vi.fn(), getSource: vi.fn(() => undefined) } as unknown as MaplibreMap;
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(deleteMutateAsync).toHaveBeenCalledWith({ datasetId: 'ds-1', gid: 7 });
  });
});

/** A map holding what the dataset preview adds for a `parcels` table of the given geometry. */
function previewMap(geometryType: string, elevationColumn?: string) {
  const sources = new Map<string, { setTiles: ReturnType<typeof vi.fn>; setData: ReturnType<typeof vi.fn> }>();
  const filters = new Map<string, unknown>();
  const map = {
    addSource: vi.fn((id: string) => {
      sources.set(id, { setTiles: vi.fn(), setData: vi.fn() });
    }),
    addLayer: vi.fn((layer: { id: string; filter?: unknown }) => {
      filters.set(layer.id, layer.filter ?? null);
    }),
    getSource: vi.fn((id: string) => sources.get(id)),
    getLayer: vi.fn((id: string) => (filters.has(id) ? { id } : undefined)),
    getFilter: vi.fn((id: string) => filters.get(id)),
    setFilter: vi.fn(),
    queryRenderedFeatures: vi.fn(() => []),
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as MaplibreMap;
  const { result } = renderHook(() =>
    useMapLayers({ tableName: 'parcels', geometryType, tileToken: null, mapRef: { current: null }, elevationColumn }),
  );
  result.current.addVectorLayers(map);
  const [vectorSourceId] = sources.keys();
  const layerIds = [...filters.keys()];
  result.current.addOverlaySource(map);
  return {
    map,
    layerIds,
    vectorSourceId,
    vectorSource: sources.get(vectorSourceId)!,
    overlay: sources.get('drawn-overlay')!,
  };
}

const PREVIEW_CASES: [label: string, geometryType: string, elevationColumn?: string][] = [
  ['point', 'MULTIPOINT'],
  ['line', 'MULTILINESTRING'],
  ['polygon', 'MULTIPOLYGON'],
  ['GEOMETRY', 'GEOMETRY'],
  ['3D polygon', 'MULTIPOLYGON', 'height_m'],
];

describe("useFeatureEditing on the dataset preview's layers", () => {
  const baseAuth = useDrawingStore.getState();

  beforeEach(() => {
    useDrawingStore.setState(baseAuth, true);
    updateMutateAsync.mockClear();
    createMutateAsync.mockClear();
  });

  it.each(PREVIEW_CASES)('restores the filter on every layer of a %s preview', (_label, geometryType, elevationColumn) => {
    const { map, layerIds } = previewMap(geometryType, elevationColumn);

    showAllFeaturesInTiles(map);

    const filtered = vi.mocked(map.setFilter).mock.calls.map(([id]) => id);
    expect(filtered.sort()).toEqual([...layerIds].sort());
  });

  it.each(PREVIEW_CASES)('hit-tests every feature layer of a %s preview', async (_label, geometryType, elevationColumn) => {
    const { map, layerIds } = previewMap(geometryType, elevationColumn);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.selectFeatureFromMap(map, FAKE_POINT);
    });

    const [[, options]] = vi.mocked(map.queryRenderedFeatures).mock.calls as unknown as [[Point, { layers: string[] }]];
    expect([...options.layers].sort()).toEqual(layerIds.filter((id) => !id.endsWith('-outline')).sort());
  });

  it('re-tiles the source the preview draws from after an attribute edit', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: { name: 'old' } } });
    const { map, vectorSource } = previewMap('MULTIPOLYGON');
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(vectorSource.setTiles).toHaveBeenCalledTimes(1);
  });

  it("clears the overlay once the preview's source reloads after a create", async () => {
    const { map, vectorSourceId, overlay } = previewMap('MULTIPOINT');
    const { result } = renderEditing(map);
    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });
    const [, onSourceData] = vi.mocked(map.on).mock.calls.find(([event]) => event === 'sourcedata') as unknown as [
      string,
      (e: { sourceId?: string; isSourceLoaded?: boolean }) => void,
    ];
    overlay.setData.mockClear();

    act(() => {
      onSourceData({ sourceId: vectorSourceId, isSourceLoaded: true });
    });

    expect(overlay.setData).toHaveBeenCalledWith({ type: 'FeatureCollection', features: [] });
  });
});

// A create whose response is lost may have committed, so every attempt to save
// one sketch sends the same key with a higher attempt number, and the server
// orders and applies the bodies. The client never writes on top of the create.
describe('useFeatureEditing — create idempotency key', () => {
  beforeEach(() => {
    createMutateAsync.mockReset();
    createMutateAsync.mockResolvedValue({});
    updateMutateAsync.mockReset();
    updateMutateAsync.mockResolvedValue({});
  });

  function sent(): { key: string; attempt: number; properties: unknown }[] {
    return createMutateAsync.mock.calls.map(([vars]) => ({
      key: vars.idempotencyKey,
      attempt: vars.attempt,
      properties: vars.properties,
    }));
  }

  it('sends one key with a higher attempt number and the current body on each attempt', async () => {
    const sketch = { type: 'Point' as const, coordinates: [0, 0] };
    createMutateAsync.mockRejectedValueOnce(new Error('timed out'));
    createMutateAsync.mockRejectedValueOnce(new Error('timed out'));
    const { result } = renderEditing(makeMapWithOverlaySource(vi.fn()));

    for (const properties of [{}, { name: 'pin' }, { name: 'edited' }]) {
      await act(async () => {
        await result.current.saveAndRefresh(sketch, properties);
      });
    }

    const attempts = sent();
    expect(attempts[0].key).toEqual(expect.any(String));
    expect(attempts[0].key).not.toBe('');
    expect(attempts.map((a) => a.key)).toEqual([attempts[0].key, attempts[0].key, attempts[0].key]);
    expect(attempts.map((a) => a.attempt)).toEqual([1, 2, 3]);
    expect(attempts.map((a) => a.properties)).toEqual([{}, { name: 'pin' }, { name: 'edited' }]);
  });

  it('sends a different key, starting again at attempt 1, for a new sketch', async () => {
    const { result } = renderEditing(makeMapWithOverlaySource(vi.fn()));

    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });
    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });

    const [first, second] = sent();
    expect(first.key).not.toBe(second.key);
    expect([first.attempt, second.attempt]).toEqual([1, 1]);
  });

  it('never writes on top of a create, however the retry came back', async () => {
    const sketch = { type: 'Point' as const, coordinates: [0, 0] };
    createMutateAsync.mockRejectedValueOnce(new Error('timed out'));
    createMutateAsync.mockResolvedValueOnce({ id: 7, properties: { name: 'first attempt' } });
    const { result } = renderEditing(makeMapWithVectorSource(vi.fn()));
    let outcome: { saved: boolean; refused?: boolean } | undefined;

    await act(async () => {
      await result.current.saveAndRefresh(sketch, { name: 'first attempt' });
    });
    await act(async () => {
      outcome = await result.current.saveAndRefresh(sketch, { name: 'edited' });
    });

    expect(updateMutateAsync).not.toHaveBeenCalled();
    expect(outcome).toEqual({ saved: true });
  });
});

// A retry the server can no longer apply comes back as a structured 409. The
// bodies below are the ones the create route sends, run through the real
// apiFetch error path.
describe('useFeatureEditing — create refused as changed or gone', () => {
  const sketch = () => ({ type: 'Point' as const, coordinates: [0, 0] });
  const CHANGED_BODY = {
    detail: {
      code: 'feature_changed',
      message: 'Someone else changed this feature after the last attempt was saved, so this attempt was not applied.',
      feature: { id: 7, geometry: { type: 'Point', coordinates: [0, 0] }, properties: {}, tile_cache_version: 55 },
    },
  };
  const GONE_BODY = {
    detail: {
      code: 'feature_gone',
      message: 'The feature created with this Idempotency-Key is gone. Use a new key to create another.',
    },
  };

  function respondWith(...replies: { status: number; body: unknown }[]) {
    const fetchMock = vi.fn();
    for (const r of replies) {
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify(r.body), { status: r.status, headers: { 'Content-Type': 'application/json' } }),
      );
    }
    vi.stubGlobal('fetch', fetchMock);
  }

  beforeEach(async () => {
    const { createFeature } = await vi.importActual<typeof import('@/api/features')>('@/api/features');
    createMutateAsync.mockReset();
    createMutateAsync.mockImplementation((v) =>
      createFeature(v.datasetId, v.geometry, v.properties, v.idempotencyKey, v.attempt),
    );
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.info).mockClear();
    vi.mocked(toast.success).mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('counts a feature_changed 409 as saved, reloads at the returned version and clears the overlay', async () => {
    respondWith({ status: 409, body: CHANGED_BODY });
    const setTiles = vi.fn();
    const overlaySetData = vi.fn();
    const map = {
      getSource: vi.fn((id: string) =>
        id === previewSourceId('parcels') ? { setTiles } : id === 'drawn-overlay' ? { setData: overlaySetData } : undefined,
      ),
      getLayer: vi.fn(() => undefined),
      setFilter: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
    } as unknown as MaplibreMap;
    const { result } = renderEditing(map);
    let outcome: { saved: boolean; refused?: boolean } | undefined;

    await act(async () => {
      outcome = await result.current.saveAndRefresh(sketch(), {});
    });

    expect(outcome).toEqual({ saved: true });
    expect(setTiles.mock.calls[0][0][0]).toMatch(/cb=55$/);
    expect(toast.info).toHaveBeenCalledWith('map.featureSavedThenChanged');
    expect(toast.error).not.toHaveBeenCalled();
    const [, onSourceData] = vi.mocked(map.on).mock.calls.find(([event]) => event === 'sourcedata') as unknown as [
      string,
      (e: { sourceId?: string; isSourceLoaded?: boolean }) => void,
    ];
    act(() => {
      onSourceData({ sourceId: previewSourceId('parcels'), isSourceLoaded: true });
    });
    expect(overlaySetData).toHaveBeenLastCalledWith({ type: 'FeatureCollection', features: [] });
  });

  it('keeps the sketch pending on a feature_gone 409 and starts a new key at attempt 1 on the next Save', async () => {
    respondWith(
      { status: 500, body: { detail: 'boom' } },
      { status: 409, body: GONE_BODY },
      { status: 201, body: { id: 9, tile_cache_version: 1 } },
    );
    const g = sketch();
    const { result } = renderEditing(makeMapWithOverlaySource(vi.fn()));
    const outcomes: { saved: boolean; refused?: boolean }[] = [];

    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        outcomes.push(await result.current.saveAndRefresh(g, {}));
      });
    }

    expect(outcomes[1]).toEqual({ saved: false, refused: true });
    expect(toast.error).toHaveBeenCalledWith('map.featureSavedThenRemoved');
    const sent = createMutateAsync.mock.calls.map(([v]) => ({ key: v.idempotencyKey, attempt: v.attempt }));
    expect(sent.map((a) => a.attempt)).toEqual([1, 2, 1]);
    expect(sent[2].key).not.toBe(sent[0].key);
    expect(outcomes[2]).toEqual({ saved: true });
  });

  it('treats a 409 without a known code as an ordinary failure', async () => {
    respondWith({ status: 409, body: { detail: 'Dataset is being replaced' } });
    const { result } = renderEditing(makeMapWithOverlaySource(vi.fn()));
    let outcome: { saved: boolean; refused?: boolean } | undefined;

    await act(async () => {
      outcome = await result.current.saveAndRefresh(sketch(), {});
    });

    expect(outcome).toEqual({ saved: false, refused: true });
    expect(toast.info).not.toHaveBeenCalled();
  });

  it('gives a stale identity no toast and no tile reload for either refusal', async () => {
    for (const body of [CHANGED_BODY, GONE_BODY]) {
      const setTiles = vi.fn();
      const { result } = renderEditing(makeMapWithVectorSource(setTiles));
      const release = deferred<Response>();
      vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(release.promise));
      const saving = result.current.saveAndRefresh(sketch(), {});
      act(() => {
        useDrawingStore.getState().bumpSessionEpoch();
      });
      release.resolve(
        new Response(JSON.stringify(body), { status: 409, headers: { 'Content-Type': 'application/json' } }),
      );
      await act(async () => {
        await saving;
      });
      expect(toast.info).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
      expect(setTiles).not.toHaveBeenCalled();
    }
  });
});

// The tile routes only recognise `_v` as a stored tile_cache_version or a
// record updated_at timestamp, so the post-edit reload must send the value
// the mutation response returns rather than a client timestamp (#2310).
describe('useFeatureEditing — tile reload carries the mutation response tile_cache_version', () => {
  beforeEach(() => {
    createMutateAsync.mockClear();
    updateMutateAsync.mockClear();
    deleteMutateAsync.mockClear();
  });

  it('saveAndRefresh (create) sends the response tile_cache_version as the tile _v', async () => {
    createMutateAsync.mockResolvedValueOnce({ id: 1, tile_cache_version: 42 });
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });

    expect(setTiles).toHaveBeenCalledTimes(1);
    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=42$/);
  });

  it('handleSaveEdit (geometry update) sends the response tile_cache_version as the tile _v', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    updateMutateAsync.mockResolvedValueOnce({ id: 7, tile_cache_version: 43 });
    const getSnapshotFeature = vi.fn(() => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: {},
    }));
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map, { getSnapshotFeature });

    await act(async () => {
      await result.current.handleSaveEdit();
    });

    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=43$/);
  });

  it('handleDeleteFeature sends the response tile_cache_version as the tile _v', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    deleteMutateAsync.mockResolvedValueOnce({ tile_cache_version: 44 });
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=44$/);
  });

  it('handleEditAttributeSubmit sends the response tile_cache_version as the tile _v', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: { name: 'old' } } });
    updateMutateAsync.mockResolvedValueOnce({ id: 7, tile_cache_version: 45 });
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=45$/);
  });

  it('falls back to a timestamp when the response has no tile_cache_version (older server)', async () => {
    createMutateAsync.mockResolvedValueOnce({ id: 1 });
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });

    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=\d+$/);
  });

  // The delete endpoint stays 204: its committed version rides a response
  // header, read by deleteFeature() in api/features.ts. Here that surfaces
  // as mutateAsync resolving to `undefined` outright (a bare 204, older
  // server or a header the client didn't get) rather than an object with a
  // null field — the hook must fall back cleanly, not crash reading a
  // property off undefined and report a successful delete as failed.
  it('falls back to a timestamp, without throwing, when a delete resolves with no result at all (bare 204)', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    deleteMutateAsync.mockResolvedValueOnce(undefined);
    // Mocks are not auto-cleared between tests in this file; other describes
    // legitimately call toast.error/toast.success for their own cases.
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
    const setTiles = vi.fn();
    const map = makeMapWithVectorSource(setTiles);
    const { result } = renderEditing(map);

    await act(async () => {
      await result.current.handleDeleteFeature();
    });

    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith('map.featureDeleted');
    expect(setTiles.mock.calls[0][0][0]).toMatch(/\/tiles\/parcels\/.*cb=\d+$/);
  });
});
