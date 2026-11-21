/**
 * Random runs of everything that can happen to the Builder's bookmarks (the
 * author edits, a save starts, is stored or fails, another editor saves, the
 * saved list is read again), checked against what the author should see.
 */
import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useBookmarksDraft } from '@/components/builder/hooks/use-bookmarks-draft';
import { sameBookmarks } from '@/lib/bookmarks';
import type { MapBookmark } from '@/types/api';

const mark = (name: string): MapBookmark => ({ name, extent: [0, 0, 1, 1] });
const LISTS: MapBookmark[][] = [[], [mark('A')], [mark('A'), mark('B')], [mark('A'), mark('C')], [mark('B'), mark('A')]];

/** A list as the server answers it. */
const stored = (list: MapBookmark[]) => list.map((item) => ({ ...item, bearing: null, pitch: null }));

function random(seed: number) {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function run(seed: number, steps: number) {
  const next = random(seed);
  const pick = <T,>(items: readonly T[]) => items[Math.floor(next() * items.length)];

  // What the server holds, and the copy of it the Builder has read.
  let server = stored(LISTS[1]);
  let shown = server;
  const { result, rerender } = renderHook(({ saved }) => useBookmarksDraft(saved, 'map-1'), {
    initialProps: { saved: shown },
  });
  // The list the author last set, until it is the same as what the server holds or is being sent.
  let intent: MapBookmark[] | null = null;
  // A save not yet answered, and the list of a stored save the Builder hasn't read back yet.
  let save: { list: MapBookmark[]; settle: (ok: boolean) => void } | null = null;
  let storedUnread: MapBookmark[] | null = null;
  const trail: string[] = [];
  const names = (list: MapBookmark[]) => list.map((item) => item.name).join('') || '-';

  for (let step = 0; step < steps; step++) {
    const event = pick(['edit', 'edit', 'begin', 'stored', 'failed', 'other', 'read', 'read'] as const);
    if (event === 'edit') {
      const list = pick(LISTS);
      act(() => result.current.setBookmarks(list));
      intent = list;
      trail.push(`edit ${names(list)}`);
    } else if (event === 'begin' && !save && result.current.bookmarksEdited) {
      const list = result.current.bookmarks;
      let settle: (ok: boolean) => void = () => {};
      act(() => {
        settle = result.current.beginSave(list);
      });
      save = { list, settle };
      trail.push(`begin ${names(list)}`);
    } else if (event === 'stored' && save) {
      const done = save;
      server = stored(done.list);
      act(() => done.settle(true));
      storedUnread = done.list;
      save = null;
      trail.push('stored');
    } else if (event === 'failed' && save) {
      const done = save;
      act(() => done.settle(false));
      save = null;
      trail.push('failed');
    } else if (event === 'other') {
      server = stored(pick(LISTS));
      trail.push(`other ${names(server)}`);
    } else if (event === 'read' && shown !== server) {
      shown = server;
      storedUnread = null;
      rerender({ saved: shown });
      trail.push('read');
    } else {
      continue;
    }

    // An edit is measured against the list being sent, else the list just
    // stored, else the list last read. One that equals its measure with no
    // save unanswered is no longer the author's edit.
    const measure = save?.list ?? storedUnread ?? shown;
    if (!save && intent && sameBookmarks(intent, measure)) intent = null;
    const context = `seed ${seed}: ${trail.join(' > ')}`;
    expect(names(result.current.bookmarks), context).toBe(names(intent ?? measure));
    expect(result.current.bookmarksEdited, context).toBe(intent !== null && !sameBookmarks(intent, measure));
  }
}

describe('useBookmarksDraft', () => {
  it('shows the author their own unsaved list and nothing stale, whatever the order of events', () => {
    for (let seed = 1; seed <= 400; seed++) run(seed, 40);
  });

  it('measures another map against its own saved list while a save of this one is unanswered', () => {
    const { result, rerender } = renderHook(({ saved, mapId }) => useBookmarksDraft(saved, mapId), {
      initialProps: { saved: stored(LISTS[1]), mapId: 'map-1' },
    });
    act(() => result.current.setBookmarks(LISTS[2]));
    act(() => {
      result.current.beginSave(result.current.bookmarks);
    });
    const other = stored(LISTS[3]);
    rerender({ saved: other, mapId: 'map-2' });
    expect(result.current.bookmarks).toBe(other);
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('keeps the edit a failed save was carrying', () => {
    const { result } = renderHook(() => useBookmarksDraft(stored(LISTS[1]), 'map-1'));
    act(() => result.current.setBookmarks(LISTS[2]));
    let settle: (ok: boolean) => void = () => {};
    act(() => {
      settle = result.current.beginSave(result.current.bookmarks);
    });
    expect(result.current.bookmarksEdited).toBe(false);
    act(() => settle(false));
    expect(result.current.bookmarks).toEqual(LISTS[2]);
    expect(result.current.bookmarksEdited).toBe(true);
  });
});
