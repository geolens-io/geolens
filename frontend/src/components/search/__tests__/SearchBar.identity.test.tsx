import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { useSearchStore } from '@/stores/search-store';
import { useAuthStore } from '@/stores/auth-store';
import { wireAuthCacheReset } from '@/lib/auth-cache-reset';
import { SearchBar } from '../SearchBar';
import type { UserResponse } from '@/types/api';

vi.mock('../SearchTypeahead', () => ({
  SearchTypeahead: () => null,
}));

/**
 * fix(#1761 review P2): deliberately does NOT mock useDebouncedValue, unlike
 * SearchBar.test.tsx — the bug this pins lives in the real 300ms window
 * between a keystroke and the debounced setQuery() call, so the test needs
 * the real timer.
 */
const initialSearchState = useSearchStore.getState();
const initialAuthState = useAuthStore.getState();

describe('SearchBar identity reset (#1761 review P2)', () => {
  beforeEach(() => {
    useSearchStore.setState(initialSearchState, true);
    useAuthStore.setState(initialAuthState, true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels a pending debounced query when identity changes before it fires', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);

    try {
      act(() => {
        useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      });
      render(<SearchBar />);

      const input = screen.getByPlaceholderText(/search the catalog/i);
      await user.type(input, 'user-1 secret');
      expect(input).toHaveValue('user-1 secret');
      // Still inside the 300ms debounce window: nothing committed yet, so
      // `q` alone gives no signal that anything changed.
      expect(useSearchStore.getState().q).toBe('');

      // Identity changes WITHOUT a page reload, before the debounce fires.
      act(() => {
        useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });
      });

      // Let the original debounce window fully elapse.
      await vi.advanceTimersByTimeAsync(500);

      expect(useSearchStore.getState().q).toBe('');
      expect(input).toHaveValue('');
    } finally {
      unsubscribe();
    }
  });
});
