import { act, renderHook, waitFor } from '@/test/test-utils';
import { useUrlSearchSync } from '@/hooks/use-url-search-sync';
import { useSearchStore } from '@/stores/search-store';

const initialSearchState = useSearchStore.getState();

describe('useUrlSearchSync', () => {
  beforeEach(() => {
    act(() => {
      useSearchStore.setState(initialSearchState, true);
    });
    window.history.replaceState({}, '', '/search');
  });

  it('restores repeated keyword params from the URL into the search store', async () => {
    window.history.replaceState(
      {},
      '',
      '/search?q=roads&keywords=wetlands&keywords=hydrology&exclude_synthetic=false',
    );

    renderHook(() => useUrlSearchSync());

    await waitFor(() => {
      expect(useSearchStore.getState().q).toBe('roads');
      expect(useSearchStore.getState().keywords).toEqual(['wetlands', 'hydrology']);
      expect(useSearchStore.getState().exclude_synthetic).toBe(false);
    });
  });

  it('keeps synchronized params on the /search workspace route', async () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState');

    renderHook(() => useUrlSearchSync());

    act(() => {
      useSearchStore.getState().setQuery('roads');
      useSearchStore.getState().setFilter('keywords', ['wetlands']);
    });

    await waitFor(() => {
      expect(replaceStateSpy).toHaveBeenLastCalledWith(
        null,
        '',
        '/search?q=roads&keywords=wetlands',
      );
    });
  });
});
