import { act, screen, fireEvent } from '@testing-library/react';
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

  // fix(#1761 review round 6): a NARROWER race than the one above — here
  // the 300ms timer fires in the SAME React batch as the identity
  // transition, rather than before it. The earlier fix canceled a
  // still-PENDING timer by changing its input; it did nothing for a
  // result that has ALREADY fired but not yet been committed, which is
  // exactly what codex reproduced by advancing the timer and switching
  // users inside one act().
  it('rejects a debounced value whose epoch is stale when the timer fires in the same batch as an identity change', async () => {
    // Deliberately NOT shouldAdvanceTime here (unlike the test above): that
    // option ticks the fake clock forward in step with real wall-clock time,
    // which let earlier debounce timers fire before this test's explicit
    // advanceTimersByTimeAsync call and made the reproduction non-
    // deterministic. This test needs precise control over exactly when the
    // 300ms elapses relative to the identity change, so it also uses
    // fireEvent (a single synchronous change) rather than userEvent.type,
    // which needs its own timer advancement between keystrokes.
    vi.useFakeTimers();
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);

    try {
      act(() => {
        useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      });
      render(<SearchBar />);

      const input = screen.getByPlaceholderText(/search the catalog/i);
      act(() => {
        fireEvent.change(input, { target: { value: 'user-1 secret' } });
      });
      expect(useSearchStore.getState().q).toBe('');

      // Identity change and the debounce timer's own commit happen inside
      // the SAME act() — the exact reproduction codex described.
      await act(async () => {
        useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });
        await vi.advanceTimersByTimeAsync(500);
      });

      // The previous identity's text must never land in the store (and by
      // extension the search request/URL), even transiently.
      expect(useSearchStore.getState().q).toBe('');
      expect(input).toHaveValue('');

      // The reset effect's own value change re-arms a fresh debounce for
      // the cleared text, which settles normally afterward.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
      expect(useSearchStore.getState().q).toBe('');
    } finally {
      unsubscribe();
    }
  });
});
