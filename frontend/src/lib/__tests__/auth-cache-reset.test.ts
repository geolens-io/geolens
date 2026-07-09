import { QueryClient } from '@tanstack/react-query';
import { wireAuthCacheReset } from '../auth-cache-reset';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

// fix(#430 codex r6): identity changes evict the whole query cache; token
// refresh (same user id) does not.
describe('wireAuthCacheReset', () => {
  const initialAuthState = useAuthStore.getState();

  afterEach(() => {
    useAuthStore.setState(initialAuthState, true);
  });

  function seed(qc: QueryClient) {
    qc.setQueryData(['search', 'maps', 'matterhorn'], { maps: [{ id: 'm1' }] });
  }

  it('clears cached queries on login and logout, but not on token refresh', () => {
    useAuthStore.setState({ token: null, user: null });
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      // Login (anonymous -> user-1): clear.
      seed(qc);
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();

      // Token refresh (same identity): keep.
      seed(qc);
      useAuthStore.setState({ token: 't2' });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeDefined();

      // Different user signs in: clear.
      useAuthStore.setState({ token: 't3', user: { id: 'user-2' } as UserResponse });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();

      // Logout: clear.
      seed(qc);
      useAuthStore.setState({ token: null, user: null });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();
    } finally {
      unsubscribe();
    }
  });
});
