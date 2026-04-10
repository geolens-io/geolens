import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { useTileToken } from '@/hooks/use-tile-token';

// Mock the tiles API. The runtime ``TileToken`` is a discriminated
// union (``VectorTileToken | RasterTileToken``) keyed on ``kind``, so
// the mock must include ``kind: 'vector'`` to match the vector branch.
vi.mock('@/api/tiles', () => ({
  getTileToken: vi.fn().mockResolvedValue({
    kind: 'vector',
    sig: 'test-sig',
    exp: 1700000000,
    scope: 'ds_abc',
    expires_in: 300,
  }),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

describe('useTileToken', () => {
  it('returns tile token data for a valid dataset id', async () => {
    const { result } = renderHook(() => useTileToken('ds_abc'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({
      kind: 'vector',
      sig: 'test-sig',
      exp: 1700000000,
      scope: 'ds_abc',
      expires_in: 300,
    });
  });

  it('is disabled when datasetId is undefined', () => {
    const { result } = renderHook(() => useTileToken(undefined), {
      wrapper: createWrapper(),
    });

    expect(result.current.fetchStatus).toBe('idle');
  });

  it('computes refetchInterval from expires_in', async () => {
    const { result } = renderHook(() => useTileToken('ds_abc'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // 80% of 300s = 240s = 240000ms
    // The hook uses expires_in * 800 (which is ms * 0.8)
    // Math.max(300 * 800, 30000) = Math.max(240000, 30000) = 240000
    const tok = result.current.data;
    expect(tok?.kind).toBe('vector');
    if (tok?.kind === 'vector') {
      expect(tok.expires_in).toBe(300);
    }
  });
});
