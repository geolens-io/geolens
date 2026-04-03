import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/auth', () => ({
  listMyApiKeys: vi.fn(),
  createMyApiKey: vi.fn(),
  revokeMyApiKey: vi.fn(),
}));

import { listMyApiKeys, createMyApiKey, revokeMyApiKey } from '@/api/auth';
import { useMyApiKeys, useCreateMyApiKey, useRevokeMyApiKey } from '@/hooks/use-api-keys';

const mockListMyApiKeys = vi.mocked(listMyApiKeys);
const mockCreateMyApiKey = vi.mocked(createMyApiKey);
const mockRevokeMyApiKey = vi.mocked(revokeMyApiKey);

describe('useMyApiKeys', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches API keys', async () => {
    const data = [{ id: 'k1', name: 'My Key', prefix: 'gl_' }];
    mockListMyApiKeys.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useMyApiKeys());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockListMyApiKeys.mockRejectedValueOnce(new Error('Unauthorized'));

    const { result } = renderHook(() => useMyApiKeys());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useCreateMyApiKey', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createMyApiKey on mutate', async () => {
    const created = { id: 'k2', name: 'New Key', key: 'gl_abc123' };
    mockCreateMyApiKey.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useCreateMyApiKey());

    await result.current.mutateAsync('New Key');

    expect(mockCreateMyApiKey).toHaveBeenCalledWith('New Key');
  });
});

describe('useRevokeMyApiKey', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls revokeMyApiKey on mutate', async () => {
    mockRevokeMyApiKey.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useRevokeMyApiKey());

    await result.current.mutateAsync('k1');

    expect(mockRevokeMyApiKey).toHaveBeenCalledWith('k1');
  });

  it('returns error state on failure', async () => {
    mockRevokeMyApiKey.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useRevokeMyApiKey());

    await expect(result.current.mutateAsync('bad-id')).rejects.toThrow('Not found');
  });
});
