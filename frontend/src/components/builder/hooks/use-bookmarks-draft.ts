import { useCallback, useEffect, useState } from 'react';
import { sameBookmarks } from '@/lib/bookmarks';
import type { MapBookmark } from '@/types/api';

interface Edit {
  mapId?: string;
  list: MapBookmark[];
}

interface Sent extends Edit {
  /** The server answered that it stored the list. */
  stored: boolean;
}

/**
 * The Builder's bookmarks: the saved list with the author's unsaved edit over it.
 *
 * An edit is measured against the list the server holds or is about to hold:
 * the list a save sent, from the moment it is sent until the saved list shows
 * it or the save fails, and the saved list otherwise. An edit equal to that
 * measure is no edit, whenever and however the two came to match (the edit put
 * back, the save's refetch, a failed save, the same list saved elsewhere), and
 * it is retired then. A list kept past that point would read as an edit again
 * on the next change from elsewhere, hide it, and go out with the next save.
 */
export function useBookmarksDraft(savedBookmarks: MapBookmark[], mapId: string | undefined) {
  const [edit, setEdit] = useState<Edit | null>(null);
  const [sent, setSent] = useState<Sent | null>(null);

  // A new saved list answers a save that was stored. One that arrives while
  // the save is still going came from elsewhere or shows the save early; the
  // save's own answer is still to come, so its list stays the measure.
  useEffect(() => {
    setSent((current) => (current?.stored ? null : current));
  }, [savedBookmarks]);

  const pending = sent && sent.mapId === mapId ? sent.list : null;
  const measure = pending ?? savedBookmarks;
  const edited = edit && edit.mapId === mapId && !sameBookmarks(edit.list, measure) ? edit.list : null;

  useEffect(() => {
    if (edit && edited === null) setEdit(null);
  }, [edit, edited]);

  const setBookmarks = useCallback((next: MapBookmark[]) => setEdit({ mapId, list: next }), [mapId]);

  /** Records a save of `list`; call the result with whether the server stored it. */
  const beginSave = useCallback(
    (list: MapBookmark[]) => {
      setSent({ mapId, list, stored: false });
      return (stored: boolean) => {
        setSent((current) => {
          if (current?.list !== list) return current;
          return stored ? { ...current, stored: true } : null;
        });
      };
    },
    [mapId],
  );

  return {
    bookmarks: edited ?? measure,
    bookmarksEdited: edited !== null,
    setBookmarks,
    beginSave,
  };
}
