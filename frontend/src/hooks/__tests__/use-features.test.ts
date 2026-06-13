import { renderHook } from '@/test/test-utils';
import { vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';

vi.mock('@/api/features', () => ({
  createFeature: vi.fn(),
  updateFeature: vi.fn(),
  deleteFeature: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  addColumn: vi.fn(),
  dropColumn: vi.fn(),
}));

import { createFeature, updateFeature, deleteFeature } from '@/api/features';
import { addColumn, dropColumn } from '@/api/datasets';
import {
  useCreateFeature,
  useUpdateFeature,
  useDeleteFeature,
  useAddColumn,
  useDropColumn,
} from '@/hooks/use-features';

const mockCreateFeature = vi.mocked(createFeature);
const mockUpdateFeature = vi.mocked(updateFeature);
const mockDeleteFeature = vi.mocked(deleteFeature);
const mockAddColumn = vi.mocked(addColumn);
const mockDropColumn = vi.mocked(dropColumn);

// BUG-038: feature/schema mutations must invalidate the column-values and
// column-stats caches (used by data-driven style editors + filter pickers,
// staleTime 5min). Pre-fix only datasets.detail + datasets.rowsPrefix were
// invalidated, so the distinct-values/min-max caches stayed stale (dropColumn
// even served values for a deleted column). Spy on the prototype since the
// test harness owns the QueryClient instance.
function spyInvalidate() {
  return vi.spyOn(QueryClient.prototype, 'invalidateQueries').mockResolvedValue(undefined);
}

function invalidatedColumnCaches(spy: ReturnType<typeof spyInvalidate>, datasetId: string) {
  const keys = spy.mock.calls.map((c) => (c[0] as { queryKey: unknown[] })?.queryKey);
  const hasValues = keys.some(
    (k) => Array.isArray(k) && k[0] === 'column-values' && k[1] === datasetId && k.length === 2,
  );
  const hasStats = keys.some(
    (k) => Array.isArray(k) && k[0] === 'column-stats' && k[1] === datasetId && k.length === 2,
  );
  return { hasValues, hasStats };
}

describe('BUG-038: column-value/stats cache invalidation', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it('useUpdateFeature invalidates the column-values + column-stats prefixes', async () => {
    const spy = spyInvalidate();
    mockUpdateFeature.mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useUpdateFeature());
    await result.current.mutateAsync({ datasetId: 'ds-9', gid: 1, properties: { a: 2 } });

    const { hasValues, hasStats } = invalidatedColumnCaches(spy, 'ds-9');
    expect(hasValues).toBe(true);
    expect(hasStats).toBe(true);
  });

  it('useCreateFeature invalidates the column caches', async () => {
    const spy = spyInvalidate();
    mockCreateFeature.mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useCreateFeature());
    await result.current.mutateAsync({ datasetId: 'ds-9', geometry: { type: 'Point', coordinates: [0, 0] } });

    const { hasValues, hasStats } = invalidatedColumnCaches(spy, 'ds-9');
    expect(hasValues).toBe(true);
    expect(hasStats).toBe(true);
  });

  it('useDeleteFeature invalidates the column caches', async () => {
    const spy = spyInvalidate();
    mockDeleteFeature.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useDeleteFeature());
    await result.current.mutateAsync({ datasetId: 'ds-9', gid: 1 });

    const { hasValues, hasStats } = invalidatedColumnCaches(spy, 'ds-9');
    expect(hasValues).toBe(true);
    expect(hasStats).toBe(true);
  });

  it('useDropColumn invalidates the column caches (deleted-column staleness)', async () => {
    const spy = spyInvalidate();
    mockDropColumn.mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useDropColumn());
    await result.current.mutateAsync({ datasetId: 'ds-9', columnName: 'gone' });

    const { hasValues, hasStats } = invalidatedColumnCaches(spy, 'ds-9');
    expect(hasValues).toBe(true);
    expect(hasStats).toBe(true);
  });

  it('useAddColumn invalidates the column caches', async () => {
    const spy = spyInvalidate();
    mockAddColumn.mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useAddColumn());
    await result.current.mutateAsync({ datasetId: 'ds-9', column: { name: 'c', type: 'text' } });

    const { hasValues, hasStats } = invalidatedColumnCaches(spy, 'ds-9');
    expect(hasValues).toBe(true);
    expect(hasStats).toBe(true);
  });
});

describe('useCreateFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createFeature on mutate', async () => {
    const created = { type: 'Feature', id: 1, geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} };
    mockCreateFeature.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useCreateFeature());

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: {},
    });

    expect(mockCreateFeature).toHaveBeenCalledWith('ds-1', { type: 'Point', coordinates: [0, 0] }, {});
  });

  it('returns error state on failure', async () => {
    mockCreateFeature.mockRejectedValueOnce(new Error('Forbidden'));

    const { result } = renderHook(() => useCreateFeature());

    await expect(
      result.current.mutateAsync({
        datasetId: 'ds-1',
        geometry: { type: 'Point', coordinates: [0, 0] },
      }),
    ).rejects.toThrow('Forbidden');
  });
});

describe('useUpdateFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls updateFeature on mutate', async () => {
    const updated = { type: 'Feature', id: 1, geometry: { type: 'Point', coordinates: [1, 1] }, properties: {} };
    mockUpdateFeature.mockResolvedValueOnce(updated as never);

    const { result } = renderHook(() => useUpdateFeature());

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      gid: 1,
      geometry: { type: 'Point', coordinates: [1, 1] },
    });

    expect(mockUpdateFeature).toHaveBeenCalledWith('ds-1', 1, { type: 'Point', coordinates: [1, 1] }, undefined);
  });
});

describe('useDeleteFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls deleteFeature on mutate', async () => {
    mockDeleteFeature.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useDeleteFeature());

    await result.current.mutateAsync({ datasetId: 'ds-1', gid: 1 });

    expect(mockDeleteFeature).toHaveBeenCalledWith('ds-1', 1);
  });

  it('returns error state on failure', async () => {
    mockDeleteFeature.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useDeleteFeature());

    await expect(result.current.mutateAsync({ datasetId: 'ds-1', gid: 99 })).rejects.toThrow('Not found');
  });
});
