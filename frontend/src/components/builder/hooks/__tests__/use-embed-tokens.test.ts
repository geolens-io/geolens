import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/embed-tokens', () => ({
  createEmbedToken: vi.fn(),
  listEmbedTokens: vi.fn(),
  updateEmbedTokenOrigins: vi.fn(),
  revokeEmbedToken: vi.fn(),
}));

import { createEmbedToken, listEmbedTokens, revokeEmbedToken } from '@/api/embed-tokens';
import { useCreateEmbedToken, useMapEmbedTokens, useRevokeEmbedToken } from '@/components/builder/hooks/use-embed-tokens';

const mockCreateEmbedToken = vi.mocked(createEmbedToken);
const mockListEmbedTokens = vi.mocked(listEmbedTokens);
const mockRevokeEmbedToken = vi.mocked(revokeEmbedToken);

describe('useMapEmbedTokens', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches embed tokens for a map', async () => {
    const data = { tokens: [{ id: 't1', token: 'abc' }], total: 1 };
    mockListEmbedTokens.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useMapEmbedTokens('m1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
    expect(mockListEmbedTokens).toHaveBeenCalledWith('m1');
  });

  it('does not fetch when mapId is undefined', () => {
    const { result } = renderHook(() => useMapEmbedTokens(undefined));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockListEmbedTokens).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockListEmbedTokens.mockRejectedValueOnce(new Error('Forbidden'));

    const { result } = renderHook(() => useMapEmbedTokens('m1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useCreateEmbedToken', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createEmbedToken on mutate', async () => {
    const created = { id: 't2', token: 'xyz', expires_at: '2026-05-01' };
    mockCreateEmbedToken.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useCreateEmbedToken());

    await result.current.mutateAsync({ mapId: 'm1', expiresInDays: 30 });

    expect(mockCreateEmbedToken).toHaveBeenCalledWith('m1', 30, undefined);
  });
});

describe('useRevokeEmbedToken', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls revokeEmbedToken on mutate', async () => {
    mockRevokeEmbedToken.mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useRevokeEmbedToken());

    await result.current.mutateAsync({ mapId: 'm1', tokenId: 't1' });

    expect(mockRevokeEmbedToken).toHaveBeenCalledWith('m1', 't1');
  });

  it('returns error state on failure', async () => {
    mockRevokeEmbedToken.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useRevokeEmbedToken());

    await expect(result.current.mutateAsync({ mapId: 'm1', tokenId: 'bad' })).rejects.toThrow('Not found');
  });
});
