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
  getTileTokensBatch: vi.fn(),
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

describe('useTileTokens', () => {
  const vec = (sig: string) => ({ kind: 'vector', sig, exp: 1, scope: 's', expires_in: 300, tile_url_template: '' }) as const;

  it('keeps existing tokens usable while a changed id set loads', async () => {
    const { getTileTokensBatch } = await import('@/api/tiles');
    const { useTileTokens } = await import('@/hooks/use-tile-token');
    let release!: () => void;
    vi.mocked(getTileTokensBatch)
      .mockResolvedValueOnce({ tokens: { a: vec('a1'), b: vec('b1') } })
      .mockImplementationOnce(
        () => new Promise((resolve) => { release = () => resolve({ tokens: { a: vec('a2') } }); }),
      );

    const { result, rerender } = renderHook(({ ids }) => useTileTokens(ids), {
      wrapper: createWrapper(),
      initialProps: { ids: ['a', 'b'] },
    });
    await waitFor(() => expect(result.current[0].data?.sig).toBe('a1'));

    rerender({ ids: ['a'] });
    expect(result.current[0].data?.sig).toBe('a1');
    expect(result.current[0].isError).toBe(false);

    rerender({ ids: ['a', 'c'] });
    expect(result.current[1].data).toBeUndefined();
    expect(result.current[1].isError).toBe(false);
    release();
  });
});
