// Uses the real TanStack mutation hooks: their isPending follows only the
// latest call, which is what overlapping writes have to survive.
import { act } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toast } from 'sonner';
import { renderHook } from '@/test/test-utils';
import { useFeatureEditing } from '@/components/dataset/hooks/use-feature-editing';
import { createFeature } from '@/api/features';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn() },
}));

vi.mock('@/api/features', () => ({
  createFeature: vi.fn(),
  updateFeature: vi.fn(),
  deleteFeature: vi.fn(),
  getFeature: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const map = {
  getSource: vi.fn(() => undefined),
  getLayer: vi.fn(() => undefined),
  on: vi.fn(),
  off: vi.fn(),
} as unknown as MaplibreMap;

describe('useFeatureEditing pending writes', () => {
  beforeEach(() => {
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
  });

  it('stays pending until overlapping creates that settle out of order have all settled', async () => {
    const first = deferred<{ id: number }>();
    const second = deferred<{ id: number }>();
    vi.mocked(createFeature)
      .mockReturnValueOnce(first.promise as ReturnType<typeof createFeature>)
      .mockReturnValueOnce(second.promise as ReturnType<typeof createFeature>);
    const { result } = renderHook(() =>
      useFeatureEditing({
        mapRef: { current: map },
        datasetId: 'ds-1',
        tableName: 'parcels',
        tileConfig: null,
        tileToken: null,
        removeFeatures: vi.fn(),
        getSnapshotFeature: vi.fn(),
        addFeatures: vi.fn(() => []),
        selectFeature: vi.fn(),
        clear: vi.fn(),
        resetHistory: vi.fn(),
      }),
    );

    let firstSave!: Promise<unknown>;
    let secondSave!: Promise<unknown>;
    act(() => {
      firstSave = result.current.saveAndRefresh({ type: 'Point', coordinates: [0, 0] }, {});
      secondSave = result.current.saveAndRefresh({ type: 'Point', coordinates: [1, 1] }, {});
    });
    expect(result.current.isFeatureMutationPending).toBe(true);

    await act(async () => {
      second.resolve({ id: 2 });
      await secondSave;
    });
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(result.current.isFeatureMutationPending).toBe(true);

    await act(async () => {
      first.reject(new Error('forbidden'));
      await firstSave;
    });
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(result.current.isFeatureMutationPending).toBe(false);
  });
});
