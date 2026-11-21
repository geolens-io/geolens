import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useControl } from '@vis.gl/react-maplibre';
import { Bookmark } from 'lucide-react';
import type { IControl, Map as MaplibreMap } from 'maplibre-gl';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { goToBookmark } from '@/lib/bookmarks';
import type { MapBookmark } from '@/types/api';

interface ViewerBookmarksMenuProps {
  bookmarks: readonly MapBookmark[];
  getMap: () => MaplibreMap | null;
}

/** The menu of a map's bookmarks; picking one moves the map there. */
export function ViewerBookmarksMenu({ bookmarks, getMap }: ViewerBookmarksMenuProps) {
  const { t } = useTranslation('common');
  const [container, setContainer] = useState<HTMLElement | null>(null);
  if (bookmarks.length === 0) return null;
  const label = t('viewer.map.bookmarks');
  return (
    <DropdownMenu
      onOpenChange={(open) => {
        // The map's own element is what fullscreen shows, so the menu mounts inside it.
        if (open) setContainer(getMap()?.getContainer() ?? null);
      }}
    >
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={label} title={label}>
          <Bookmark className="m-auto size-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" container={container} className="max-h-72 w-56 max-w-[calc(100vw-2rem)]">
        {bookmarks.map((bookmark, index) => (
          <DropdownMenuItem
            // Bookmarks carry no id; the list is read-only here.
            key={index}
            title={bookmark.name}
            onSelect={() => {
              const map = getMap();
              if (map) goToBookmark(map, bookmark);
            }}
          >
            <span className="truncate">{bookmark.name}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

class SlotControl implements IControl {
  readonly element = document.createElement('div');

  constructor() {
    this.element.className = 'maplibregl-ctrl maplibregl-ctrl-group';
  }

  onAdd() {
    return this.element;
  }

  onRemove() {
    this.element.remove();
  }
}

/**
 * Puts the bookmarks button in the map's top-right control column, under the
 * zoom, fullscreen and terrain buttons, so it never lands on another control.
 */
export function ViewerBookmarks({ bookmarks, getMap }: ViewerBookmarksMenuProps) {
  const control = useControl(() => new SlotControl(), { position: 'top-right' });
  if (bookmarks.length === 0) return null;
  return createPortal(<ViewerBookmarksMenu bookmarks={bookmarks} getMap={getMap} />, control.element);
}
