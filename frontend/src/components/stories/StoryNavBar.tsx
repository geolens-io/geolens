import { useState } from 'react';
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

  const list = (
    <ol className={cn(collapsed ? 'space-y-1 px-2' : 'flex min-w-0 flex-1 items-center gap-1 overflow-x-auto')}>
      {chapters.map((chapter, i) => (
        <li key={chapter.id} className="shrink-0">
          <Button
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
