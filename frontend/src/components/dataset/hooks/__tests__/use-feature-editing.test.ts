// BUG-042: editing a feature's ATTRIBUTES never reloaded the vector tiles, so
// attribute-driven rendering kept stale values until a manual reload. The
// geometry/delete handlers already reloadTiles(); the attribute handler now
// does too. This test pins that handleEditAttributeSubmit cache-busts the
// vector tile source after a successful update.
import { renderHook, act } from '@testing-library/react';
import type { Map as MaplibreMap, Point } from 'maplibre-gl';
import { toast } from 'sonner';
import { useFeatureEditing } from '@/components/dataset/hooks/use-feature-editing';
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

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: (table: string, _token: unknown, _base: unknown, cacheBust?: string) =>
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
      id === 'vector-tile-source' ? { setTiles } : undefined,
    ),
    getLayer: vi.fn(() => undefined),
    setFilter: vi.fn(),
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
}

function renderEditing(map: MaplibreMap, overrides: EditingOverrides = {}) {
  const mapRef = { current: map };
  const opts = {
    removeFeatures: overrides.removeFeatures ?? vi.fn(),
    getSnapshotFeature: overrides.getSnapshotFeature ?? vi.fn(),
    addFeatures: overrides.addFeatures ?? vi.fn(() => []),
    selectFeature: overrides.selectFeature ?? vi.fn(),
    clear: overrides.clear ?? vi.fn(),
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
      onSourceData({ sourceId: 'vector-tile-source', isSourceLoaded: true });
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

  it('returns applied: true on a real failure, preserving the pre-existing close-on-error behavior', async () => {
    useDrawingStore.setState({ selectedFeature: { gid: 7, tdId: 'td-7', properties: {} } });
    updateMutateAsync.mockRejectedValueOnce(new Error('boom'));
    const map = makeMapWithVectorSource(vi.fn());
    const { result } = renderEditing(map);

    let outcome: { applied: boolean } | undefined;
    await act(async () => {
      outcome = await result.current.handleEditAttributeSubmit({ name: 'new' });
    });

    expect(outcome).toEqual({ applied: true });
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
    await act(async () => {
      await saving;
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('saveAndRefresh (create) still reports a real failure when the identity has not changed', async () => {
    const overlaySetData = vi.fn();
    const map = makeMapWithOverlaySource(overlaySetData);
    const { result } = renderEditing(map);

    createMutateAsync.mockRejectedValueOnce(new Error('boom'));

    await act(async () => {
      await result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
    });

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
});
