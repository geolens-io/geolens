import { memo, useRef } from 'react';
import { AlertTriangle, ArrowDown, ArrowUp, MapPin, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { StoryChapter } from '@/types/api';
import { MAX_CHAPTERS } from './story-draft';
import { useMoveFocus } from './use-move-focus';

interface ChapterListProps {
  chapters: StoryChapter[];
  selected: number;
  onSelect: (index: number) => void;
  onMove: (index: number, by: -1 | 1) => void;
  onRemove: (index: number) => void;
  onAdd: () => void;
  /** False at the chapter cap. */
  canAdd: boolean;
  /** Chapters whose scene map wasn't found on the last save. */
  missingMapChapterIds: ReadonlySet<string>;
}

/** The story's chapters in order, with select, reorder and delete. Every action is a button, so it works from the keyboard. */
export const ChapterList = memo(function ChapterList({
  chapters,
  selected,
  onSelect,
  onMove,
  onRemove,
  onAdd,
  canAdd,
  missingMapChapterIds,
}: ChapterListProps) {
  const { t } = useTranslation('stories');
  const listRef = useRef<HTMLOListElement>(null);
  const markMoved = useMoveFocus(listRef, 'data-chapter-id', chapters);

  function move(chapter: StoryChapter, index: number, by: -1 | 1) {
    markMoved(chapter.id, by);
    onMove(index, by);
  }

  return (
    <nav aria-label={t('editor.chapters.label')} className="space-y-2">
      <ol ref={listRef} className="space-y-1">
        {chapters.map((chapter, i) => {
          const name = chapter.title || t('reader.untitledChapter', { index: i + 1 });
          return (
            <li
              key={chapter.id}
              data-chapter-id={chapter.id}
              className={cn(
                'flex items-center gap-1 rounded-md border px-1',
                i === selected ? 'border-primary bg-accent' : 'border-transparent',
              )}
            >
              <button
                type="button"
                data-chapter-select
                aria-current={i === selected ? 'true' : undefined}
                onClick={() => onSelect(i)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-sm px-2 py-1.5 text-start text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="readout w-5 shrink-0 text-xs text-muted-foreground">{i + 1}</span>
                <span className="truncate">{name}</span>
                {(chapter.scene || chapter.scene_hidden) && (
                  <>
                    <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="sr-only">{t('editor.chapters.hasScene')}</span>
                  </>
                )}
                {missingMapChapterIds.has(chapter.id) && (
                  <>
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
                    <span className="sr-only">{t('editor.chapters.mapMissing')}</span>
                  </>
                )}
              </button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                data-move="-1"
                disabled={i === 0}
                aria-label={t('editor.chapters.moveUp', { title: name })}
                onClick={() => move(chapter, i, -1)}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                data-move="1"
                disabled={i === chapters.length - 1}
                aria-label={t('editor.chapters.moveDown', { title: name })}
                onClick={() => move(chapter, i, 1)}
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 hover:text-destructive"
                aria-label={t('editor.chapters.remove', { title: name })}
                onClick={() => onRemove(i)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          );
        })}
      </ol>
      <Button type="button" variant="outline" size="sm" onClick={onAdd} disabled={!canAdd} data-chapter-add>
        <Plus className="h-4 w-4" aria-hidden="true" />
        {t('editor.chapters.add')}
      </Button>
      {!canAdd && <p className="text-xs text-muted-foreground">{t('editor.limits.chapters', { count: MAX_CHAPTERS })}</p>}
    </nav>
  );
});
