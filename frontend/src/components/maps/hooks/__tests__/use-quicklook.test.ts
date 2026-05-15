import { renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';

// vi.mock factories are hoisted to top of file, so we cannot reference outer
// class declarations in the factory. Define ApiError inline in the factory and
// also export it so tests can construct instances via the mocked module.
vi.mock('@/api/client', () => {
  class ApiError extends Error {
    status: number;
    constructor(m: string, s: number) {
      super(m);
      this.name = 'ApiError';
      this.status = s;
    }
  }
  return {
    apiFetchBlob: vi.fn(),
    ApiError,
  };
});

import { apiFetchBlob, ApiError } from '@/api/client';
import { _resetQuicklookCache, markQuicklookMissing } from '@/lib/quicklook-cache';
import { useQuicklook } from '@/components/maps/hooks/use-quicklook';

const mockApiFetchBlob = vi.mocked(apiFetchBlob);

const fakeBlob = new Blob(['img'], { type: 'image/png' });

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:http://localhost/quicklook');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  _resetQuicklookCache();
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetQuicklookCache();
});

describe('useQuicklook', () => {
  // Test 1: null datasetId returns idle
  it('returns idle when datasetId is null', () => {
    const { result } = renderHook(() => useQuicklook(null), {
      wrapper: createWrapper(),
    });

    expect(result.current).toEqual({ url: null, status: 'idle' });
    expect(mockApiFetchBlob).not.toHaveBeenCalled();
  });

  // Test 2: already known missing returns missing synchronously
  it('returns missing synchronously when datasetId is already known missing', () => {
    const id = 'dataset-known-missing';
    markQuicklookMissing(id);

    const { result } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });

    expect(result.current).toEqual({ url: null, status: 'missing' });
    expect(mockApiFetchBlob).not.toHaveBeenCalled();
  });

  // Test 3: successful fetch returns blob URL with status ready
  it('returns blob URL with status ready on successful fetch', async () => {
    mockApiFetchBlob.mockResolvedValueOnce(fakeBlob);

    const id = 'dataset-success';
    const { result } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });

    expect(result.current.status).toBe('loading');

    await waitFor(() => expect(result.current.status).toBe('ready'));

    expect(result.current.url).toBe('blob:http://localhost/quicklook');
    expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  // Test 4: ApiError 404 -> missing status + markQuicklookMissing called
  it('returns missing and calls markQuicklookMissing on 404', async () => {
    const id = 'dataset-404';
    mockApiFetchBlob.mockRejectedValueOnce(new ApiError('Not Found', 404));

    const { result } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.status).toBe('missing'));

    expect(result.current.url).toBeNull();
    // After being marked missing, the cache should record it
    // Re-render should return missing without another fetch
    const { result: result2 } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });
    expect(result2.current).toEqual({ url: null, status: 'missing' });
    // apiFetchBlob should NOT have been called a second time (negative-cached)
    expect(mockApiFetchBlob).toHaveBeenCalledTimes(1);
  });

  // Test 5: non-404 error -> status error, markQuicklookMissing NOT called
  it('returns error status for non-404 errors without calling markQuicklookMissing', async () => {
    const id = 'dataset-500';
    mockApiFetchBlob.mockRejectedValueOnce(new ApiError('Server Error', 500));

    const { result } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.status).toBe('error'));

    expect(result.current.url).toBeNull();

    // Confirm it's NOT negative-cached — re-render with a fresh wrapper allows another fetch
    const secondWrapper = createWrapper();
    mockApiFetchBlob.mockRejectedValueOnce(new ApiError('Server Error', 500));
    const { result: result2 } = renderHook(() => useQuicklook(id), {
      wrapper: secondWrapper,
    });
    await waitFor(() => expect(result2.current.status).toBe('error'));
    // apiFetchBlob was called again (not cached as missing)
    expect(mockApiFetchBlob).toHaveBeenCalledTimes(2);
  });

  // Test 6: unmount revokes blob URL
  it('revokes blob URL on unmount', async () => {
    mockApiFetchBlob.mockResolvedValueOnce(fakeBlob);

    const id = 'dataset-unmount';
    const { result, unmount } = renderHook(() => useQuicklook(id), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.url).toBe('blob:http://localhost/quicklook'));

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/quicklook');
  });

  // Test 7: dataset id change revokes old blob URL and fetches new one
  it('revokes old blob URL and fetches new one when datasetId changes', async () => {
    mockApiFetchBlob.mockResolvedValue(fakeBlob);

    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => useQuicklook(id),
      { initialProps: { id: 'dataset-a' }, wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.url).toBe('blob:http://localhost/quicklook'));

    rerender({ id: 'dataset-b' });

    await waitFor(() => {
      expect(mockApiFetchBlob).toHaveBeenCalledTimes(2);
    });

    // revokeObjectURL was called when the query key changed (data changed)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/quicklook');
  });

  // Test 8: apiFetchBlob called with the exact path (proves Bearer-attaching wrapper is used)
  it('calls apiFetchBlob with the exact quicklook path', async () => {
    mockApiFetchBlob.mockResolvedValueOnce(fakeBlob);

    const id = '777ddb26-0000-0000-0000-000000000000';
    const { result } = renderHook(() => useQuicklook(id, 256), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.status).toBe('ready'));

    expect(mockApiFetchBlob).toHaveBeenCalledWith(
      `/api/datasets/${id}/quicklook?size=256`,
    );
  });
});
