import { QueryClient } from '@tanstack/react-query';
import { renderHook } from '@/test/test-utils';
import { useInvalidateAuthProviders } from '@/hooks/use-auth-providers';
import { queryKeys } from '@/lib/query-keys';

describe('useInvalidateAuthProviders', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it('invalidates the admin provider table and the login page buttons together', () => {
    const invalidateQueries = vi
      .spyOn(QueryClient.prototype, 'invalidateQueries')
      .mockResolvedValue(undefined);
    const { result } = renderHook(() => useInvalidateAuthProviders());

    result.current();

    // fix(#1117): the pairing IS the fix — the admin surfaces already hit the first
    // key and the bug was the second one going unrefreshed.
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.settingsOAuth.providers,
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.authConfig.oauthProviders,
    });
  });

  it('returns a stable callback so mutation options do not churn', () => {
    const { result, rerender } = renderHook(() => useInvalidateAuthProviders());
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});
