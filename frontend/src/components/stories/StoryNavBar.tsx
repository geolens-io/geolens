import { useEffect, useRef, useState } from 'react';
import { Menu } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import type { StoryChapter } from '@/types/api';
import { chapterTitle } from './StoryChapterBody';

interface StoryNavBarProps {
  title: string;
  chapters: readonly StoryChapter[];
  active: number;
  onSelect: (index: number) => void;
  /** Moves the chapter list into a menu. */
  collapsed: boolean;
}

/** The story's title and a list of its chapters, the open one marked. Choosing one opens it. */
export function StoryNavBar({ title, chapters, active, onSelect, collapsed }: StoryNavBarProps) {
  const { t } = useTranslation('stories');
  const [open, setOpen] = useState(false);
  const activeRef = useRef<HTMLButtonElement>(null);
  // Titles past the bar's edge scroll under the fade; keep the open chapter in sight.
  useEffect(() => {
    if (!collapsed) activeRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [active, collapsed]);

  const [listEl, setListEl] = useState<HTMLOListElement | null>(null);
  const [fade, setFade] = useState({ start: false, end: false });
  // The fade only marks a side that has tabs hidden past it.
  useEffect(() => {
    if (!listEl || collapsed) return;
    const update = () => {
      const max = listEl.scrollWidth - listEl.clientWidth;
      const offset = Math.abs(listEl.scrollLeft);
      const next = { start: offset > 1, end: max - offset > 1 };
      setFade((prev) => (prev.start === next.start && prev.end === next.end ? prev : next));
    };
    update();
    listEl.addEventListener('scroll', update, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(listEl);
    // The list keeps its box when a tab grows, as when a font loads; the tabs report that.
    for (const tab of listEl.children) observer?.observe(tab);
    return () => {
      listEl.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, [listEl, collapsed, chapters]);

  const list = (
    <ol
      ref={setListEl}
      className={cn(
        collapsed
          ? 'min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-4'
          : 'flex min-w-0 flex-1 items-center gap-1 overflow-x-auto scroll-px-8',
        !collapsed && fade.start && !fade.end && '[mask-image:linear-gradient(to_right,transparent,black_2rem)]',
        !collapsed && !fade.start && fade.end && '[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]',
        !collapsed && fade.start && fade.end && '[mask-image:linear-gradient(to_right,transparent,black_2rem,black_calc(100%-2rem),transparent)]',
      )}
    >
      {chapters.map((chapter, i) => (
        <li key={chapter.id} className="shrink-0">
          <Button
            ref={i === active ? activeRef : undefined}
            variant="ghost"
            size="sm"
            aria-current={i === active ? 'step' : undefined}
            className={cn(
              'max-w-[16rem] justify-start',
              collapsed && 'w-full max-w-none',
              i === active && 'bg-accent font-semibold text-accent-foreground',
            )}
            onClick={() => {
              setOpen(false);
              onSelect(i);
            }}
          >
            <span className="truncate">{chapterTitle(chapter, i, t)}</span>
          </Button>
        </li>
      ))}
    </ol>
  );

  return (
    <nav aria-label={t('reader.chaptersLabel')} className="flex items-center gap-4 border-b bg-background px-4 py-2">
      <p className="min-w-0 truncate text-sm font-semibold text-foreground md:max-w-[16rem] md:shrink-0">{title}</p>
      {collapsed ? (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="sm" className="ms-auto">
              <Menu className="h-4 w-4" aria-hidden="true" />
              {t('reader.stepperLabel')}
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64">
            <SheetHeader>
              <SheetTitle>{title}</SheetTitle>
              <SheetDescription className="sr-only">{t('reader.chaptersLabel')}</SheetDescription>
            </SheetHeader>
            {list}
          </SheetContent>
        </Sheet>
      ) : (
        list
      )}
    </nav>
  );
}
