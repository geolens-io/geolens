import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode, type Ref } from 'react';
import type { PaddingOptions } from 'maplibre-gl';
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
import { readerLogoUrl, readerThemeStyle, type ReaderTheme } from '@/lib/reader-theme';
import { useTheme } from '@/components/theme-provider';
import { cn } from '@/lib/utils';
import type { StoryChapter, StorySettings } from '@/types/api';
import { chapterHeadingId, chapterTitle, StoryChapterBody } from './StoryChapterBody';
import { StoryMapPane } from './StoryMapPane';
import { StoryNavBar } from './StoryNavBar';
import { activeChapterFrom, nearestSceneChapter, nextMapScene } from './story-scenes';

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
  /** More actions beside the title, such as the embed snippet. */
  headerActions?: ReactNode;
  /** A branding extension's accent, font and logo for this page. */
  readerTheme?: ReaderTheme | null;
  /** Null or absent means every default. */
  settings?: StorySettings | null;
  /** The reader is the whole page, as in an embed, so it has no edit link or header actions. */
  chromeless?: boolean;
}

type PanelPosition = StorySettings['panel_position'];

interface PanelProps extends Omit<StoryReaderProps, 'settings' | 'chromeless'> {
  active: number;
  onActiveChange: (index: number) => void;
  /** No chapter has a scene, so the text has the page to itself. */
  textOnly: boolean;
  ref?: Ref<ScrollPanelHandle>;
  /** Set when the panel floats over a full-bleed map. */
  floating?: PanelPosition;
  /** A floating panel with nothing to show leaves the map clear but stays scrollable. */
  bare?: boolean;
  /** Height of the docked Map data panel a floating panel must end above. */
  clearance?: number;
}

interface ScrollPanelHandle {
  /** Scrolls so the chapter is the one the reader is on. */
  scrollToChapter(index: number): void;
  /** The scrolling panel, for measuring how much map it covers. */
  element(): HTMLElement | null;
}

// Floating panels sit clear of the map's layers button at the top left and its
// zoom controls at the top right, and stop short of the Map data button.
const FLOATING_PLACEMENT: Record<PanelPosition, string> = {
  left: 'left-14',
  right: 'right-14',
  // Below lg a centred panel would meet the legend, so it sits as the right one does.
  center: 'right-14 lg:right-auto lg:left-1/2 lg:-translate-x-1/2',
};
const FLOATING_BASE = 'absolute top-3 z-[5] max-w-[calc(100%-24rem)] rounded-lg border bg-card text-card-foreground shadow-lg';

/**
 * Opens a link in a chromeless reader in a new tab. Every other GeoLens page
 * refuses to be framed, and the embed snippet's sandbox allows popups but not
 * navigating the host page. A link to a place on this page still follows.
 */
function openLinkOutsideFrame(event: MouseEvent<HTMLElement>) {
  const link = (event.target as Element).closest?.('a[href]');
  if (!(link instanceof HTMLAnchorElement) || link.getAttribute('href')!.startsWith('#')) return;
  event.preventDefault();
  window.open(link.href, '_blank', 'noopener,noreferrer');
}

// Space kept between a floating panel and the scene's centre area.
const PANEL_GAP_PX = 16;
const NO_PADDING: PaddingOptions = { top: 0, bottom: 0, left: 0, right: 0 };

/** The side padding that centres a scene in the map a floating panel leaves free. */
function panelPadding(panel: DOMRect, map: DOMRect): PaddingOptions {
  if (panel.width === 0 || map.width === 0) return NO_PADDING;
  // A centred panel leaves both sides the same, so it asks for none.
  if (Math.abs(panel.left + panel.width / 2 - (map.left + map.width / 2)) < 1) return NO_PADDING;
  const onLeft = panel.left + panel.width / 2 < map.left + map.width / 2;
  return onLeft
    ? { ...NO_PADDING, left: Math.round(panel.right - map.left + PANEL_GAP_PX) }
    : { ...NO_PADDING, right: Math.round(map.right - panel.left + PANEL_GAP_PX) };
}

function isTextless(chapter: StoryChapter): boolean {
  return !chapter.title?.trim() && !chapter.blocks?.length;
}

/**
 * Reads a published story. Wide screens scroll the chapters beside a fixed
 * map, and the chapter in view sets the scene; narrow screens step through
 * one chapter at a time.
 */
export function StoryReader({
  storyId,
  coverAssetId,
  title,
  summary,
  chapters,
  editHref,
  headerActions,
  readerTheme,
  settings,
  chromeless = false,
}: StoryReaderProps) {
  const { t } = useTranslation('stories');
  const queryClient = useQueryClient();
  const isNarrow = useIsMobile();
  const { resolvedTheme } = useTheme();
  const [position, setPosition] = useState<Position>(null);
  const active = activeIndex(chapters, position);
  const sceneChapter = useMemo(() => nearestSceneChapter(chapters, active), [chapters, active]);
  // nearestSceneChapter looks both ways, so null means no chapter has a scene.
  const textOnly = sceneChapter === null;
  const scroller = useRef<ScrollPanelHandle>(null);
  const floating = !isNarrow && !textOnly && settings?.layout === 'floating' ? settings.panel_position : undefined;
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

  const currentMapId = resolved?.scene.map_id;
  const next = useMemo(() => nextMapScene(chapters, active, currentMapId), [chapters, active, currentMapId]);
  const nextMapId = next?.scene.map_id;
  useEffect(() => {
    if (nextMapId) void prefetchMap(queryClient, nextMapId);
  }, [queryClient, nextMapId]);

  const chapter = chapters[active];
  const announcement = position
    ? t('reader.chapterAnnouncement', {
        index: active + 1,
        total: chapters.length,
        title: chapterTitle(chapter, active, t),
      })
    : '';

  const bare = floating !== undefined && isTextless(chapter);
  const [dataPanelHeight, setDataPanelHeight] = useState(0);
  const mapArea = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState(NO_PADDING);
  // Measured, not derived from rem widths: the panel's width changes at lg and its max-width caps it.
  useLayoutEffect(() => {
    const panel = floating ? scroller.current?.element() : null;
    const area = mapArea.current;
    if (!panel || !area) {
      setMeasured(NO_PADDING);
      return;
    }
    const measure = () => {
      const next = panelPadding(panel.getBoundingClientRect(), area.getBoundingClientRect());
      setMeasured((prev) => (prev.left === next.left && prev.right === next.right ? prev : next));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(panel);
    observer.observe(area);
    return () => observer.disconnect();
  }, [floating, textOnly]);
  // A textless chapter hides the panel, so its scene fills the map.
  const padding = bare ? NO_PADDING : measured;
  const selectChapter = (index: number) => {
    changeChapter(index);
    scroller.current?.scrollToChapter(index);
  };

  const panelProps = {
    storyId,
    coverAssetId,
    title,
    summary,
    chapters,
    editHref: chromeless ? undefined : editHref,
    headerActions: chromeless ? undefined : headerActions,
    readerTheme,
    active,
    onActiveChange: changeChapter,
    textOnly,
  };
  return (
    <div
      className="flex min-h-0 w-full flex-1 flex-col"
      style={readerThemeStyle(readerTheme, resolvedTheme)}
      onClickCapture={chromeless ? openLinkOutsideFrame : undefined}
    >
      {settings?.navigation && (
        <StoryNavBar title={title} chapters={chapters} active={active} onSelect={selectChapter} collapsed={isNarrow} />
      )}
      {/* The map stays the second child in every layout, so a resize across the
          breakpoint doesn't remount it; flex-col-reverse puts it on top when narrow. */}
      <div className={cn('flex min-h-0 w-full flex-1 flex-col-reverse md:flex-row', floating && 'relative')}>
        {isNarrow ? (
          <StoryStepper {...panelProps} />
        ) : (
          <StoryScrollPanel ref={scroller} {...panelProps} floating={floating} bare={bare} clearance={floating ? dataPanelHeight : 0} />
        )}
        {bare && floating && (
          // The hidden panel no longer takes the wheel, so these move between chapters instead.
          <div
            role="group"
            aria-label={t('reader.stepperLabel')}
            className={cn('absolute top-3 z-[6] flex gap-1 rounded-lg border bg-card p-1 shadow-lg', FLOATING_PLACEMENT[floating])}
          >
            <Button variant="ghost" size="sm" aria-disabled={active === 0} onClick={() => selectChapter(active - 1)}>
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              {t('reader.previous')}
            </Button>
            <Button variant="ghost" size="sm" aria-disabled={active === chapters.length - 1} onClick={() => selectChapter(active + 1)}>
              {t('reader.next')}
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        )}
        {!textOnly && (
          <div
            ref={mapArea}
            className={cn(
              floating ? 'absolute inset-0' : 'relative h-[45vh] shrink-0 md:h-auto md:min-w-0 md:flex-1',
            )}
          >
            <StoryMapPane
              resolved={resolved}
              next={next}
              emptyHint={sceneChapter?.scene_hidden ? t('reader.sceneUnavailable') : undefined}
              legendSide={floating === 'left' ? 'end' : undefined}
              panel={floating}
              defaultTransition={settings?.transition}
              padding={floating ? padding : undefined}
              onDataPanelHeightChange={floating ? setDataPanelHeight : undefined}
            />
          </div>
        )}
        <LiveAnnouncement text={announcement} />
      </div>
    </div>
  );
}

function StoryHeader({
  storyId,
  coverAssetId,
  title,
  summary,
  editHref,
  headerActions,
  logoUrl,
}: {
  storyId: string;
  coverAssetId?: string | null;
  title: string;
  summary: string | null;
  editHref?: string;
  headerActions?: ReactNode;
  logoUrl?: string;
}) {
  const { t } = useTranslation('stories');
  return (
    <header className="space-y-2">
      {logoUrl && (
        // Decorative: a brand mark beside the title, not content.
        <img src={logoUrl} alt="" referrerPolicy="no-referrer" className="h-6 w-auto max-w-32 object-contain" />
      )}
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
        {(headerActions || editHref) && (
          <div className="flex shrink-0 gap-2">
            {headerActions}
            {editHref && (
              <Button asChild variant="outline" size="sm">
                <Link to={editHref}>
                  <Pencil className="h-4 w-4" aria-hidden="true" />
                  {t('reader.edit')}
                </Link>
              </Button>
            )}
          </div>
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
  headerActions,
  readerTheme,
  active,
  onActiveChange,
  textOnly,
  ref,
  floating,
  bare,
  clearance = 0,
}: PanelProps) {
  const { t } = useTranslation('stories');
  const panelRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<(HTMLElement | null)[]>([]);
  const frame = useRef<number | null>(null);
  const jumpedTo = useRef<number | null>(null);
  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);

  // The chapter's top goes to the panel's top, but never so far that the next
  // chapter crosses the line, which would hand the scene to it.
  const scrollToChapter = useCallback((index: number) => {
    const panel = panelRef.current;
    const section = sectionRefs.current[index];
    if (!panel || !section) return;
    const offset = (el: HTMLElement) => el.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
    let top = offset(section);
    const next = sectionRefs.current[index + 1];
    if (next) top = Math.min(top, offset(next) - panel.clientHeight * ACTIVE_LINE);
    panel.scrollTo?.({ top: Math.max(0, top), behavior: 'instant' });
    jumpedTo.current = panel.scrollTop;
  }, []);
  useImperativeHandle(ref, () => ({ scrollToChapter, element: () => panelRef.current }), [scrollToChapter]);

  // A change of the panel's height (the Map data panel docking, a resize) moves
  // the activation line; scrolling by the same amount keeps the text that was on
  // the line there, or the next scroll would hand the chapter back to the one before.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || typeof ResizeObserver === 'undefined') return;
    let last = panel.clientHeight;
    const observer = new ResizeObserver(() => {
      const now = panel.clientHeight;
      if (now !== last) {
        panel.scrollTop += (last - now) * ACTIVE_LINE;
        // A jump's settle guard follows the compensated position; only the reader's own scroll clears it.
        if (jumpedTo.current !== null) jumpedTo.current = panel.scrollTop;
      }
      last = now;
    });
    observer.observe(panel);
    return () => observer.disconnect();
  }, []);

  // Opening this layout on a later chapter (a phone stepper widened past the
  // breakpoint) starts with that chapter in view, so text and scene agree.
  useLayoutEffect(() => {
    if (active !== 0) scrollToChapter(active);
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
      // The settle of a jump keeps the chosen chapter even when the clamp left the next one above the line.
      if (jumpedTo.current !== null) {
        if (Math.abs(panel.scrollTop - jumpedTo.current) < 1) return;
        jumpedTo.current = null;
      }
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
      tabIndex={bare ? undefined : 0}
      inert={bare}
      role="region"
      aria-label={t('reader.chaptersLabel')}
      // A floor keeps the chapters readable in a short embed, over the docked panel if it must.
      style={floating ? { height: `max(8rem, min(48rem, calc(100% - 5rem - ${clearance}px)))` } : undefined}
      className={cn(
        // Positioned, so a block's visually hidden live region stays in the scroll box instead of stretching the page.
        'relative min-h-0 overflow-y-auto focus-visible:outline-2 focus-visible:outline-ring',
        floating
          ? cn(
              FLOATING_BASE,
              // A bare panel shows nothing, so its scrollbar must not sit over the map.
              !bare && 'story-floating-scroll',
              FLOATING_PLACEMENT[floating],
              'w-[26rem] lg:w-[30rem]',
              bare && 'pointer-events-none overflow-y-hidden border-transparent bg-transparent shadow-none [&>*]:opacity-0',
            )
          : cn('bg-background', textOnly ? 'flex-1' : 'w-[26rem] shrink-0 border-e lg:w-[30rem]'),
      )}
    >
      <div className={cn('space-y-10 p-6', textOnly && 'mx-auto max-w-2xl')}>
        <StoryHeader
          storyId={storyId}
          coverAssetId={coverAssetId}
          title={title}
          summary={summary}
          editHref={editHref}
          headerActions={headerActions}
          logoUrl={readerLogoUrl(readerTheme)}
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
  headerActions,
  readerTheme,
  active,
  onActiveChange,
  textOnly,
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
    // A focused box that scrolls sideways, such as a wide code block, keeps its arrow keys.
    const target = event.target;
    if (target instanceof HTMLElement && target !== event.currentTarget && target.scrollWidth > target.clientWidth) return;
    event.preventDefault();
    onActiveChange(event.key === 'ArrowRight' ? active + 1 : active - 1);
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- arrow keys step chapters from any control focused inside the stepper
    <div
      role="group"
      aria-label={t('reader.stepperLabel')}
      onKeyDown={handleKeyDown}
      className={cn('flex min-h-0 flex-1 flex-col bg-background', !textOnly && 'border-t')}
    >
      <div
        ref={contentRef}
        role="region"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the named overflow region must be keyboard-scrollable
        tabIndex={0}
        aria-labelledby={chapterHeadingId(chapter)}
        className="relative min-h-0 flex-1 space-y-4 overflow-y-auto p-4 focus-visible:outline-2 focus-visible:outline-ring"
      >
        <StoryHeader
          storyId={storyId}
          coverAssetId={isFirst ? coverAssetId : null}
          title={title}
          summary={isFirst ? summary : null}
          editHref={editHref}
          headerActions={headerActions}
          logoUrl={readerLogoUrl(readerTheme)}
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
