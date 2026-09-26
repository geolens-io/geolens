import { useEffect } from 'react';

/** `null`/`undefined` leaves `document.title` untouched; `''` resets it to
 *  the bare fallback instead — the two are not the same "no title" case. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (title == null) return;
    document.title = title ? `${title} - GeoLens` : 'GeoLens';
  }, [title]);
}
