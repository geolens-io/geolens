import { useCallback, useEffect, useState } from 'react';
import { sameBookmarks } from '@/lib/bookmarks';
import type { MapBookmark } from '@/types/api';

interface Edit {
  mapId?: string;
  list: MapBookmark[];
}

/** What the server holds, or may come to hold, that the saved list doesn't show yet. */
interface Ahead {
  mapId?: string;
  /** The list of a save not yet answered. */
  sending: MapBookmark[] | null;
  /** The list of the last stored save, until the saved list is read again. */
  stored: MapBookmark[] | null;
}

const NOTHING_AHEAD: Ahead = { sending: null, stored: null };

/**
 * The Builder's bookmarks: the saved list with the author's unsaved edit over it.
 *
 * An edit is measured against the list the server holds or is about to hold:
 * the list a save is sending, else the list the last save stored, else the
 * saved list as last read. An edit equal to that measure is no edit, whenever
 * and however the two came to match (the edit put back, a stored save, a
 * failed save, the same list saved elsewhere), and it is retired once no save
 * of it is still unanswered. A list kept past that point would read as an edit
 * again on the next change from elsewhere, hide it, and go out with the next
 * save.
 */
export function useBookmarksDraft(savedBookmarks: MapBookmark[], mapId: string | undefined) {
  const [edit, setEdit] = useState<Edit | null>(null);
  const [aheadState, setAhead] = useState<Ahead>(NOTHING_AHEAD);
  const ahead = aheadState.mapId === mapId ? aheadState : NOTHING_AHEAD;

  // A saved list read again shows what the last stored save left, or what
  // someone else saved after it. A save still unanswered is not answered by it.
  useEffect(() => {
    setAhead((current) => (current.stored ? { ...current, stored: null } : current));
  }, [savedBookmarks]);

  const measure = ahead.sending ?? ahead.stored ?? savedBookmarks;
  const edited = edit && edit.mapId === mapId && !sameBookmarks(edit.list, measure) ? edit.list : null;

  // While a save is unanswered its list is only what the server may come to
  // hold, so the edit it carries stays in hand: a save that fails gives the
  // measure back, and the edit is an edit again.
  const unanswered = ahead.sending !== null;
  useEffect(() => {
    if (edit && edited === null && !unanswered) setEdit(null);
  }, [edit, edited, unanswered]);

  const setBookmarks = useCallback((next: MapBookmark[]) => setEdit({ mapId, list: next }), [mapId]);

  /** Records a save of `list`; call the result with whether the server stored it. */
  const beginSave = useCallback(
    (list: MapBookmark[]) => {
      setAhead((current) => ({
        mapId,
        sending: list,
        stored: current.mapId === mapId ? current.stored : null,
      }));
      return (stored: boolean) => {
        setAhead((current) => {
          if (current.mapId !== mapId || current.sending !== list) return current;
          return { ...current, sending: null, stored: stored ? list : current.stored };
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
