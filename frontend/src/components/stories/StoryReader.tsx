import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { storyAssetPath } from '@/api/stories';
import { AssetImage } from '@/components/widgets/image/AssetImage';
import { prefetchMap } from '@/hooks/use-maps';
import { useIsMobile } from '@/hooks/use-mobile';
import type { StoryChapter } from '@/types/api';
import { chapterHeadingId, StoryChapterBody } from './StoryChapterBody';
import { StoryMapPane } from './StoryMapPane';
import { activeChapterFrom, nearestSceneChapter, nextSceneMapId } from './story-scenes';

// A chapter becomes active once its top passes 40% of the panel's height.
const ACTIVE_LINE = 0.4;

type Position = { id: string; index: number } | null;

/**
 * The chapter a reader is on. Tracked by id, so a refetch that reorders or
 * removes chapters keeps the reader on the same chapter, or the nearest
 * position when it's gone. Null until the reader moves: the first chapter.
 */
function activeIndex(chapters: readonly StoryChapter[], position: Position): number {
  if (!position) return 0;
  const found = chapters.findIndex((c) => c.id === position.id);
  return found >= 0 ? found : Math.max(0, Math.min(position.index, chapters.length - 1));
}

interface StoryReaderProps {
  storyId: string;
  coverAssetId?: string | null;
  title: string;
  summary: string | null;
  chapters: StoryChapter[];
  /** The editor, for a reader who may edit the story. */
  editHref?: string;
}

interface PanelProps extends StoryReaderProps {
  active: number;
  onActiveChange: (index: number) => void;
}

/**
 * Reads a published story. Wide screens scroll the chapters beside a fixed
 * map, and the chapter in view sets the scene; narrow screens step through
 * one chapter at a time.
 */
export function StoryReader({ storyId, coverAssetId, title, summary, chapters, editHref }: StoryReaderProps) {
  const { t } = useTranslation('stories');
  const queryClient = useQueryClient();
  const isNarrow = useIsMobile();
  const [position, setPosition] = useState<Position>(null);
  const active = activeIndex(chapters, position);
  const sceneChapter = useMemo(() => nearestSceneChapter(chapters, active), [chapters, active]);
  const scene = sceneChapter?.scene;
  const sceneChapterId = sceneChapter?.id;
  const resolved = useMemo(
    () => (scene && sceneChapterId ? { scene, chapterId: sceneChapterId } : null),
    [scene, sceneChapterId],
  );

  // Moving to the chapter already open changes nothing, so it isn't announced.
  const changeChapter = useCallback(
    (index: number) => {
      if (index < 0 || index >= chapters.length) return;
      setPosition((prev) => (index === activeIndex(chapters, prev) ? prev : { id: chapters[index].id, index }));
    },
    [chapters],
  );

  const nextMapId = nextSceneMapId(chapters, active, resolved?.scene.map_id);
  useEffect(() => {
    if (nextMapId) void prefetchMap(queryClient, nextMapId);
  }, [queryClient, nextMapId]);

  const chapter = chapters[active];
  const announcement = position
    ? t('reader.chapterAnnouncement', {
        index: active + 1,
        total: chapters.length,
        title: chapter.title || t('reader.untitledChapter', { index: active + 1 }),
      })
    : '';

  const panelProps = {
    storyId,
    coverAssetId,
    title,
    summary,
    chapters,
    editHref,
    active,
    onActiveChange: changeChapter,
  };
  return (
    // The map stays the second child in both layouts, so a resize across the
    // breakpoint doesn't remount it; flex-col-reverse puts it on top when narrow.
    <div className="flex min-h-0 w-full flex-1 flex-col-reverse md:flex-row">
      {isNarrow ? <StoryStepper {...panelProps} /> : <StoryScrollPanel {...panelProps} />}
      <div className="relative h-[45vh] shrink-0 md:h-auto md:min-w-0 md:flex-1">
        <StoryMapPane
          resolved={resolved}
          emptyHint={sceneChapter?.scene_hidden ? t('reader.sceneUnavailable') : undefined}
        />
      </div>
      <LiveAnnouncement text={announcement} />
    </div>
  );
}

function StoryHeader({
  storyId,
  coverAssetId,
  title,
  summary,
  editHref,
}: {
  storyId: string;
  coverAssetId?: string | null;
  title: string;
  summary: string | null;
  editHref?: string;
}) {
  const { t } = useTranslation('stories');
  return (
    <header className="space-y-2">
      {coverAssetId && (
        // Decorative beside the title.
        <AssetImage
          path={storyAssetPath(storyId, coverAssetId)}
          alt=""
          className="aspect-[2/1] w-full rounded-md object-cover"
          placeholderClassName="aspect-[2/1] w-full"
          fallback={null}
        />
      )}
      <div className="flex items-start justify-between gap-2">
        <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
        {editHref && (
          <Button asChild variant="outline" size="sm" className="shrink-0">
            <Link to={editHref}>
              <Pencil className="h-4 w-4" aria-hidden="true" />
              {t('reader.edit')}
            </Link>
          </Button>
        )}
      </div>
      {summary && <p className="text-sm text-muted-foreground">{summary}</p>}
    </header>
  );
}

function StoryScrollPanel({
  storyId,
  coverAssetId,
  title,
  summary,
  chapters,
  editHref,
  active,
  onActiveChange,
}: PanelProps) {
  const { t } = useTranslation('stories');
  const panelRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<(HTMLElement | null)[]>([]);
  const frame = useRef<number | null>(null);
  // The panel's scroll position after it scrolled to the open chapter on mount.
  const restoredTop = useRef<number | null>(null);
  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);

  // Opening this layout on a later chapter (a phone stepper widened past the
  // breakpoint) starts with that chapter in view, so text and scene agree.
  useLayoutEffect(() => {
    const section = sectionRefs.current[active];
    if (active === 0 || !section) return;
    section.scrollIntoView({ block: 'start', behavior: 'instant' });
    restoredTop.current = panelRef.current?.scrollTop ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on mount; afterwards scrolling sets the chapter
  }, []);

  // Measures every chapter against the line once per frame while scrolling,
  // so a jump (Home, a scrollbar drag) lands on the right chapter too.
  const handleScroll = useCallback(() => {
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const panel = panelRef.current;
      if (!panel) return;
      // The scroll from that restore isn't the reader's: a short chapter would
      // otherwise hand the scene to the one after it.
      if (restoredTop.current !== null && panel.scrollTop === restoredTop.current) return;
      restoredTop.current = null;
      const line = panel.getBoundingClientRect().top + panel.clientHeight * ACTIVE_LINE;
      const crossed = sectionRefs.current
        .slice(0, chapters.length)
        .map((section) => !!section && section.getBoundingClientRect().top < line);
      onActiveChange(activeChapterFrom(crossed));
    });
  }, [chapters, onActiveChange]);

  return (
    <div
      ref={panelRef}
      onScroll={handleScroll}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the named overflow region must be keyboard-scrollable
      tabIndex={0}
      role="region"
      aria-label={t('reader.chaptersLabel')}
      className="min-h-0 w-[26rem] shrink-0 overflow-y-auto border-e bg-background focus-visible:outline-2 focus-visible:outline-ring lg:w-[30rem]"
    >
      <div className="space-y-10 p-6">
        <StoryHeader
          storyId={storyId}
          coverAssetId={coverAssetId}
          title={title}
          summary={summary}
          editHref={editHref}
        />
        {chapters.map((chapter, i) => (
          <section
            key={chapter.id}
            ref={(el) => {
              sectionRefs.current[i] = el;
            }}
            aria-labelledby={chapterHeadingId(chapter)}
            aria-current={i === active ? 'step' : undefined}
            className={`space-y-3 border-s-2 ps-4 transition-colors ${i === active ? 'border-primary' : 'border-transparent'}`}
          >
            <StoryChapterBody storyId={storyId} chapter={chapter} index={i} />
          </section>
        ))}
        {/* Lets the last chapter scroll up to the line that makes it active. */}
        <div aria-hidden="true" className="h-[60vh]" />
      </div>
    </div>
  );
}

function StoryStepper({
  storyId,
  coverAssetId,
  title,
  summary,
  chapters,
  editHref,
  active,
  onActiveChange,
}: PanelProps) {
  const { t } = useTranslation('stories');
  const contentRef = useRef<HTMLDivElement>(null);
  const isFirst = active === 0;
  const isLast = active === chapters.length - 1;
  const chapter = chapters[active];

  useEffect(() => {
    contentRef.current?.scrollTo?.({ top: 0 });
  }, [active]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    onActiveChange(event.key === 'ArrowRight' ? active + 1 : active - 1);
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- arrow keys step chapters from any control focused inside the stepper
    <div
      role="group"
      aria-label={t('reader.stepperLabel')}
      onKeyDown={handleKeyDown}
      className="flex min-h-0 flex-1 flex-col border-t bg-background"
    >
      <div
        ref={contentRef}
        role="region"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the named overflow region must be keyboard-scrollable
        tabIndex={0}
        aria-labelledby={chapterHeadingId(chapter)}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 focus-visible:outline-2 focus-visible:outline-ring"
      >
        <StoryHeader
          storyId={storyId}
          coverAssetId={isFirst ? coverAssetId : null}
          title={title}
          summary={isFirst ? summary : null}
          editHref={editHref}
        />
        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t('reader.chapterOf', { index: active + 1, total: chapters.length })}
          </p>
          <StoryChapterBody storyId={storyId} chapter={chapter} index={active} />
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 border-t p-2">
        {/* aria-disabled keeps focus on the button at either end. */}
        <Button
          variant="outline"
          size="sm"
          aria-disabled={isFirst}
          className="aria-disabled:opacity-50"
          onClick={() => onActiveChange(active - 1)}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {t('reader.previous')}
        </Button>
        <span className="readout text-xs text-muted-foreground" aria-hidden="true">
          {active + 1} / {chapters.length}
        </span>
        <Button
          variant="outline"
          size="sm"
          aria-disabled={isLast}
          className="aria-disabled:opacity-50"
          onClick={() => onActiveChange(active + 1)}
        >
          {t('reader.next')}
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
