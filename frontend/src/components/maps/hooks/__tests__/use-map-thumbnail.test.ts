import { renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';

vi.mock('@/api/client', () => ({
  apiFetchBlob: vi.fn(),
}));

import { apiFetchBlob } from '@/api/client';
import { useMapThumbnail } from '@/components/maps/hooks/use-map-thumbnail';

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
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:http://localhost/thumb');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useMapThumbnail', () => {
  it('returns null initially then blob URL after fetch', async () => {
    mockApiFetchBlob.mockResolvedValueOnce(fakeBlob);

    const { result } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail/'), {
      wrapper: createWrapper(),
    });

    expect(result.current).toBeNull();

    await waitFor(() => expect(result.current).toBe('blob:http://localhost/thumb'));
    expect(mockApiFetchBlob).toHaveBeenCalledWith('/api/maps/1/thumbnail/');
    expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);
  });

  it('returns null when thumbnailUrl is null', () => {
    const { result } = renderHook(() => useMapThumbnail(null), {
      wrapper: createWrapper(),
    });
    expect(result.current).toBeNull();
    expect(mockApiFetchBlob).not.toHaveBeenCalled();
  });

  it('returns null when fetch fails', async () => {
    mockApiFetchBlob.mockRejectedValueOnce(new Error('404'));

    const { result } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail/'), {
      wrapper: createWrapper(),
    });

    // Query stays null on error (default value)
    await waitFor(() => expect(mockApiFetchBlob).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('returns blob URL for different thumbnailUrl', async () => {
    mockApiFetchBlob.mockResolvedValue(fakeBlob);

    const { result, rerender } = renderHook(
      ({ url }: { url: string }) => useMapThumbnail(url),
      { initialProps: { url: '/api/maps/1/thumbnail/' }, wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current).toBe('blob:http://localhost/thumb'));

    rerender({ url: '/api/maps/2/thumbnail/' });

    await waitFor(() => {
      expect(mockApiFetchBlob).toHaveBeenCalledTimes(2);
      expect(result.current).toBe('blob:http://localhost/thumb');
    });
  });
});
