import { renderHook, waitFor, act } from '@testing-library/react';
import { vi } from 'vitest';

vi.mock('@/api/client', () => ({
  apiFetchBlob: vi.fn(),
}));

import { apiFetchBlob } from '@/api/client';
import { useMapThumbnail } from '@/hooks/use-map-thumbnail';

const mockApiFetchBlob = vi.mocked(apiFetchBlob);

const fakeBlob = new Blob(['img'], { type: 'image/png' });

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

    const { result } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail'));

    expect(result.current).toBeNull();

    await waitFor(() => expect(result.current).toBe('blob:http://localhost/thumb'));
    expect(mockApiFetchBlob).toHaveBeenCalledWith('/api/maps/1/thumbnail');
    expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);
  });

  it('returns null when thumbnailUrl is null', () => {
    const { result } = renderHook(() => useMapThumbnail(null));
    expect(result.current).toBeNull();
    expect(mockApiFetchBlob).not.toHaveBeenCalled();
  });

  it('returns null when fetch fails', async () => {
    mockApiFetchBlob.mockRejectedValueOnce(new Error('404'));

    const { result } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail'));

    // Wait for the rejected promise to settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(result.current).toBeNull();
  });

  it('revokes previous blob URL when thumbnailUrl changes', async () => {
    mockApiFetchBlob.mockResolvedValue(fakeBlob);

    const { result, rerender } = renderHook(
      ({ url }: { url: string }) => useMapThumbnail(url),
      { initialProps: { url: '/api/maps/1/thumbnail' } },
    );

    await waitFor(() => expect(result.current).toBe('blob:http://localhost/thumb'));

    rerender({ url: '/api/maps/2/thumbnail' });

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/thumb');
  });

  it('revokes blob URL on unmount', async () => {
    mockApiFetchBlob.mockResolvedValueOnce(fakeBlob);

    const { result, unmount } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail'));

    await waitFor(() => expect(result.current).toBe('blob:http://localhost/thumb'));

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/thumb');
  });

  it('does not set state after unmount (cancelled fetch)', async () => {
    let resolveBlob: (b: Blob) => void;
    mockApiFetchBlob.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveBlob = resolve;
      }),
    );

    const { result, unmount } = renderHook(() => useMapThumbnail('/api/maps/1/thumbnail'));

    unmount();

    // Resolve after unmount — should not create a blob URL
    await act(async () => {
      resolveBlob!(fakeBlob);
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(result.current).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
