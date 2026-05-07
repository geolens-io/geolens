import { useEffect, useRef } from 'react';
import { useSearchStore } from '@/stores/search-store';

// CLEAN-N6: the search workspace lives at the root path after the landing
// page was removed. Previously this was "/search" with a redirect shim.
const SEARCH_WORKSPACE_PATH = '/';

/**
 * Two-way sync between the search store and URL search params.
 * On mount: restores store state from URL params.
 * On store change: pushes state to URL via replaceState.
 */
export function useUrlSearchSync() {
  const isRestoringRef = useRef(false);

  // On mount: read URL params and restore into store
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const parsed: Record<string, string> = {};
    const keywordsList: string[] = [];

    params.forEach((value, key) => {
      if (key === 'keywords') {
        keywordsList.push(value);
      } else {
        parsed[key] = value;
      }
    });

    if (keywordsList.length > 0) {
      parsed.keywords = keywordsList.join(',');
    }

    if (Object.keys(parsed).length > 0) {
      isRestoringRef.current = true;
      useSearchStore.getState().restoreParams(parsed);
      requestAnimationFrame(() => {
        isRestoringRef.current = false;
      });
    }
  }, []);

  // Subscribe to store changes and push to URL
  useEffect(() => {
    const unsub = useSearchStore.subscribe(() => {
      if (isRestoringRef.current) return;

      const storeParams = useSearchStore.getState().toParams();
      const urlParams = new URLSearchParams();
      for (const [key, value] of Object.entries(storeParams)) {
        if (key === 'keywords' && value) {
          // Use repeated params to match API format for bookmarkability
          for (const kw of value.split(',')) {
            if (kw) urlParams.append('keywords', kw);
          }
        } else {
          urlParams.set(key, value);
        }
      }
      const search = urlParams.toString();

      window.history.replaceState(
        null,
        '',
        search ? `${SEARCH_WORKSPACE_PATH}?${search}` : SEARCH_WORKSPACE_PATH,
      );
    });

    return unsub;
  }, []);
}
