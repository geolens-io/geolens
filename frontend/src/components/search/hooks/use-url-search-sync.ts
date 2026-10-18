import { useEffect, useRef } from 'react';
import { useSearchStore } from '@/stores/search-store';

// The search workspace lives at the root path.
const SEARCH_WORKSPACE_PATH = '/';

/**
 * Two-way sync between the search store and URL search params.
 * On mount: restores store state from URL params.
 * On store change: pushes state to URL via replaceState.
 */
export function useUrlSearchSync() {
  const isRestoringRef = useRef(false);

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

  useEffect(() => {
    const unsub = useSearchStore.subscribe(() => {
      if (isRestoringRef.current) return;

      const storeParams = useSearchStore.getState().toParams();
      const urlParams = new URLSearchParams();
      for (const [key, value] of Object.entries(storeParams)) {
        if (key === 'keywords' && value) {
          // Repeated params match the API format and keep URLs bookmarkable.
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
