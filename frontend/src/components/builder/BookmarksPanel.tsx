import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Bookmark, Navigation, Plus, Trash2 } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { bookmarkFromMap, goToBookmark, MAX_BOOKMARK_NAME, MAX_BOOKMARKS } from '@/lib/bookmarks';
import type { MapBookmark } from '@/types/api';

interface BookmarksPanelProps {
  bookmarks: readonly MapBookmark[];
  onChange: (next: MapBookmark[]) => void;
  map: MaplibreMap | null;
}

type FocusTarget = { index: number; control: 'name' | 'up' | 'down' | 'delete' } | 'add';

export function BookmarksPanel({ bookmarks, onChange, map }: BookmarksPanelProps) {
  const { t } = useTranslation('builder');
  const reasonId = useId();
  const addRef = useRef<HTMLButtonElement>(null);
  const rowRefs = useRef<Array<HTMLLIElement | null>>([]);
  const [pendingFocus, setPendingFocus] = useState<FocusTarget | null>(null);

  const atLimit = bookmarks.length >= MAX_BOOKMARKS;
  const addDisabled = !map || atLimit;

  useEffect(() => {
    if (!pendingFocus) return;
    setPendingFocus(null);
    if (pendingFocus === 'add') {
      addRef.current?.focus();
      return;
    }
    const row = rowRefs.current[pendingFocus.index];
    if (pendingFocus.control === 'name') {
      const input = row?.querySelector<HTMLInputElement>('input');
      input?.focus();
      input?.select();
      return;
    }
    row?.querySelector<HTMLElement>(`[data-bookmark-control="${pendingFocus.control}"]`)?.focus();
  }, [pendingFocus]);

  const add = () => {
    if (!map || atLimit) return;
    const name = t('bookmarks.defaultName', { number: bookmarks.length + 1 });
    onChange([...bookmarks, bookmarkFromMap(map, name)]);
    setPendingFocus({ index: bookmarks.length, control: 'name' });
  };

  const rename = (index: number, name: string) => {
    onChange(bookmarks.map((b, i) => (i === index ? { ...b, name } : b)));
  };

  const move = (index: number, by: -1 | 1) => {
    const target = index + by;
    const next = [...bookmarks];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
    // A button that is now disabled can't hold focus, so use its sibling.
    const control = by === -1 ? (target === 0 ? 'down' : 'up') : target === bookmarks.length - 1 ? 'up' : 'down';
    setPendingFocus({ index: target, control });
  };

  const remove = (index: number) => {
    onChange(bookmarks.filter((_, i) => i !== index));
    setPendingFocus(index < bookmarks.length - 1 ? { index, control: 'delete' } : 'add');
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <Button
        ref={addRef}
        type="button"
        variant="outline"
        size="sm"
        disabled={addDisabled}
        aria-describedby={addDisabled ? reasonId : undefined}
        onClick={add}
      >
        <Plus aria-hidden="true" />
        {t('bookmarks.add')}
      </Button>
      {addDisabled && (
        <p id={reasonId} className={atLimit ? 'text-xs text-muted-foreground' : 'sr-only'}>
          {atLimit ? t('bookmarks.limitReached', { count: MAX_BOOKMARKS }) : t('bookmarks.addNoMap')}
        </p>
      )}
      {bookmarks.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center text-muted-foreground">
          <Bookmark className="h-5 w-5" aria-hidden="true" />
          <p className="max-w-[16rem] text-sm">{t('bookmarks.empty')}</p>
        </div>
      ) : (
        <ul aria-label={t('bookmarks.listLabel')} className="space-y-2">
          {bookmarks.map((bookmark, index) => (
            <BookmarkRow
              // Bookmarks carry no id, and a row's only state is its draft name.
              key={index}
              ref={(el) => {
                rowRefs.current[index] = el;
              }}
              bookmark={bookmark}
              index={index}
              count={bookmarks.length}
              map={map}
              onRename={rename}
              onMove={move}
              onRemove={remove}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

interface BookmarkRowProps {
  bookmark: MapBookmark;
  index: number;
  count: number;
  map: MaplibreMap | null;
  onRename: (index: number, name: string) => void;
  onMove: (index: number, by: -1 | 1) => void;
  onRemove: (index: number) => void;
  ref: React.Ref<HTMLLIElement>;
}

function BookmarkRow({ bookmark, index, count, map, onRename, onMove, onRemove, ref }: BookmarkRowProps) {
  const { t } = useTranslation('builder');
  const [draft, setDraft] = useState(bookmark.name);
  const nameAtFocus = useRef(bookmark.name);
  // A name that changed outside the field (a move, a save's reply) replaces
  // the draft; the field's own typing already matches it.
  useEffect(() => {
    setDraft((current) => (current.trim() === bookmark.name ? current : bookmark.name));
  }, [bookmark.name]);

  // Each keystroke reaches the list, so a save made from the keyboard while
  // the field has focus carries the name on screen.
  const type = (value: string) => {
    setDraft(value);
    const name = value.trim();
    if (name && name !== bookmark.name) onRename(index, name);
  };

  const settle = () => {
    if (draft.trim()) {
      setDraft(bookmark.name);
      return;
    }
    setDraft(nameAtFocus.current);
    if (nameAtFocus.current !== bookmark.name) onRename(index, nameAtFocus.current);
  };

  const name = bookmark.name;
  return (
    <li ref={ref} className="space-y-1.5 rounded-md border p-2">
      <Input
        value={draft}
        maxLength={MAX_BOOKMARK_NAME}
        aria-label={t('bookmarks.nameLabel', { number: index + 1 })}
        onFocus={() => {
          nameAtFocus.current = bookmark.name;
        }}
        onChange={(e) => type(e.target.value)}
        onBlur={settle}
      />
      <div className="flex items-center justify-end gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          data-bookmark-control="go"
          disabled={!map}
          aria-label={t('bookmarks.goTo', { name })}
          title={t('bookmarks.goTo', { name })}
          onClick={() => map && goToBookmark(map, bookmark)}
        >
          <Navigation aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          data-bookmark-control="up"
          disabled={index === 0}
          aria-label={t('bookmarks.moveUp', { name })}
          title={t('bookmarks.moveUp', { name })}
          onClick={() => onMove(index, -1)}
        >
          <ArrowUp aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          data-bookmark-control="down"
          disabled={index === count - 1}
          aria-label={t('bookmarks.moveDown', { name })}
          title={t('bookmarks.moveDown', { name })}
          onClick={() => onMove(index, 1)}
        >
          <ArrowDown aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          data-bookmark-control="delete"
          aria-label={t('bookmarks.delete', { name })}
          title={t('bookmarks.delete', { name })}
          onClick={() => onRemove(index)}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
    </li>
  );
}
