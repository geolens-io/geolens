import userEvent from '@testing-library/user-event';
import { act, fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { StoryReader } from '../StoryReader';
import type { ResolvedScene } from '../story-scenes';
import type { StoryChapter, StoryScene, StorySettings } from '@/types/api';

const layout = vi.hoisted(() => ({ narrow: true }));
const pane = vi.hoisted(() => ({
  resolved: null as ResolvedScene | null,
  next: null as ResolvedScene | null,
  hint: undefined as string | undefined,
  legendSide: undefined as string | undefined,
  panel: undefined as string | undefined,
  defaultTransition: undefined as string | undefined,
}));

const prefetch = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => layout.narrow }));
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: async () => new Blob(['x'], { type: 'image/webp' }),
}));
vi.mock('@/hooks/use-maps', () => ({ prefetchMap: (_qc: unknown, id: string) => prefetch(id) }));
vi.mock('../StoryMapPane', () => ({
  StoryMapPane: ({ resolved, next, emptyHint, legendSide, panel, defaultTransition }: { resolved: ResolvedScene | null; next?: ResolvedScene | null; emptyHint?: string; legendSide?: string; panel?: string; defaultTransition?: string }) => {
    pane.resolved = resolved;
    pane.next = next ?? null;
    pane.legendSide = legendSide;
    pane.panel = panel;
    pane.defaultTransition = defaultTransition;
    pane.hint = emptyHint;
    return <div data-testid="story-map" />;
  },
}));

function scene(mapId: string): StoryScene {
  return { map_id: mapId, camera: { center: [0, 0], zoom: 3, bearing: 0, pitch: 0 }, layer_visibility: {} };
}

function markdown(id: string, text: string) {
  return { id, type: 'markdown' as const, v: 1 as const, title: null, config: { text } };
}

const CHAPTERS: StoryChapter[] = [
  { id: 'c1', title: 'The tracks', scene: scene('map-a'), scene_hidden: false, blocks: [markdown('00000000-0000-4000-8000-000000000001', 'First text')] },
  { id: 'c2', title: 'The coasts', scene: scene('map-b'), scene_hidden: false, blocks: [markdown('00000000-0000-4000-8000-000000000002', 'Second text')] },
  { id: 'c3', title: null, scene: null, scene_hidden: false, blocks: [markdown('00000000-0000-4000-8000-000000000003', 'Third text')] },
  { id: 'c4', title: 'Gone', scene: null, scene_hidden: true, blocks: [markdown('00000000-0000-4000-8000-000000000004', 'Fourth text')] },
];

function renderReader() {
  return render(<StoryReader storyId="s1" title="Hurricanes" summary="Where they go" chapters={CHAPTERS} />);
}

beforeEach(() => {
  pane.defaultTransition = undefined;
  layout.narrow = true;
  pane.resolved = null;
  prefetch.mockReset();
});

it('loads the next scene map ahead of the reader', async () => {
  const user = userEvent.setup();
  renderReader();
  expect(prefetch).toHaveBeenCalledWith('map-b');
  await user.click(screen.getByRole('button', { name: /Next/ }));
  expect(prefetch).toHaveBeenCalledTimes(1);
});

it('hands the pane the next scene on another map to load behind the current one', async () => {
  const user = userEvent.setup();
  renderReader();
  expect(pane.next).toEqual({ scene: CHAPTERS[1].scene, chapterId: 'c2' });
  await user.click(screen.getByRole('button', { name: /Next/ }));
  expect(pane.next).toBeNull();
});

describe('narrow stepper', () => {
  it('steps through chapters with the arrow keys and moves the scene', async () => {
    const user = userEvent.setup();
    renderReader();
    expect(screen.getByRole('heading', { level: 2, name: 'The tracks' })).toBeInTheDocument();
    expect(pane.resolved?.chapterId).toBe('c1');

    await user.click(screen.getByRole('region', { name: 'The tracks' }));
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('heading', { level: 2, name: 'The coasts' })).toBeInTheDocument();
    expect(pane.resolved?.scene.map_id).toBe('map-b');

    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('heading', { level: 2, name: 'The tracks' })).toBeInTheDocument();
    expect(pane.resolved?.scene.map_id).toBe('map-a');
  });

  it('keeps the previous scene on a text-only chapter and shows its text', async () => {
    const user = userEvent.setup();
    renderReader();
    await user.click(screen.getByRole('button', { name: /Next/ }));
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByRole('heading', { level: 2, name: 'Chapter 3' })).toBeInTheDocument();
    expect(screen.getByText('Third text')).toBeInTheDocument();
    expect(pane.resolved).toEqual({ scene: CHAPTERS[1].scene, chapterId: 'c2' });
  });

  it("shows no earlier scene for a chapter whose map the reader can't open, and says why", async () => {
    const user = userEvent.setup();
    renderReader();
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByRole('heading', { level: 2, name: 'Gone' })).toBeInTheDocument();
    expect(screen.getByText(/unavailable or has been deleted, so the chapter/)).toBeInTheDocument();
    expect(pane.resolved).toBeNull();
    expect(pane.hint).toBe("This chapter's map is unavailable or has been deleted.");
  });

  it('stays on the last chapter and keeps focus on Next at the end', async () => {
    const user = userEvent.setup();
    renderReader();
    const next = screen.getByRole('button', { name: /Next/ });
    for (let i = 0; i < 4; i++) await user.click(next);
    expect(screen.getByRole('heading', { level: 2, name: 'Gone' })).toBeInTheDocument();
    expect(next).toHaveAttribute('aria-disabled', 'true');
    expect(next).toHaveFocus();
  });
});

describe('chapter announcements', () => {
  it('announces each chapter change, and not the opening chapter', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      renderReader();
      act(() => vi.runOnlyPendingTimers());
      expect(screen.getByRole('status')).toBeEmptyDOMElement();

      await user.click(screen.getByRole('button', { name: /Next/ }));
      act(() => vi.runOnlyPendingTimers());
      expect(screen.getByRole('status')).toHaveTextContent('Chapter 2 of 4: The coasts');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('wide scrolling panel', () => {
  // A panel at y = 100, 416 px wide and 1000 px high unless a test says
  // otherwise, so the 40% line sits at y = 500.
  async function scrollTo(tops: number[], size = { width: 416, height: 1000 }) {
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: size.height });
    Object.defineProperty(panel, 'clientWidth', { configurable: true, value: size.width });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: tops[i] }) as DOMRect;
    });
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  }

  it('makes the chapter whose top has crossed 40% of the panel active', async () => {
    layout.narrow = false;
    renderReader();
    expect(pane.resolved?.chapterId).toBe('c1');

    await scrollTo([-500, 300, 1400, 2400]);
    expect(pane.resolved?.chapterId).toBe('c2');
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');

    await scrollTo([-500, 550, 1650, 2650]);
    expect(pane.resolved?.chapterId).toBe('c1');
  });

  it("puts the line at 40% of the panel's height, not its width", async () => {
    layout.narrow = false;
    renderReader();
    // 800 px high: the line is at 100 + 320 = 420; 40% of the 416 px width would put it at 266.
    await scrollTo([-500, 400, 1400, 2400], { width: 416, height: 800 });
    expect(pane.resolved?.chapterId).toBe('c2');

    await scrollTo([-500, 440, 1440, 2440], { width: 416, height: 800 });
    expect(pane.resolved?.chapterId).toBe('c1');
  });

  it('measures every chapter again after a jump', async () => {
    layout.narrow = false;
    renderReader();
    await scrollTo([-3000, -2000, -1000, 200]);
    expect(screen.getByRole('region', { name: 'Gone' })).toHaveAttribute('aria-current', 'step');

    // Home: every chapter moves below the line in one scroll.
    await scrollTo([150, 900, 1800, 2700]);
    expect(screen.getByRole('region', { name: 'The tracks' })).toHaveAttribute('aria-current', 'step');
    expect(pane.resolved?.chapterId).toBe('c1');
  });

  it("doesn't announce the opening chapter when the reader scrolls within it", async () => {
    layout.narrow = false;
    renderReader();
    await scrollTo([140, 900, 1800, 2700]);
    await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('stays on the open chapter, or the nearest one, when a refetch changes the chapters', async () => {
    layout.narrow = false;
    const { rerender } = renderReader();
    await scrollTo([-500, 300, 1400, 2400]);
    rerender(<StoryReader storyId="s1" title="Hurricanes" summary={null} chapters={[CHAPTERS[1], CHAPTERS[0]]} />);
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');
  });
});

describe('switching layouts', () => {
  const realScrollTo = Element.prototype.scrollTo;
  const realRect = Element.prototype.getBoundingClientRect;
  afterEach(() => {
    Element.prototype.scrollTo = realScrollTo;
    Element.prototype.getBoundingClientRect = realRect;
  });

  it('opens the wide layout scrolled to the chapter the stepper was on', async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollTo = scrolled;
    // The panel starts at 100; each chapter starts 900 px below the one before.
    Element.prototype.getBoundingClientRect = function (this: Element) {
      if (this.tagName !== 'SECTION') return { top: 100 } as DOMRect;
      const index = Array.from(this.parentElement!.querySelectorAll('section')).indexOf(this as HTMLElement);
      return { top: 600 + index * 900 } as DOMRect;
    };
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 1000 });
    const user = userEvent.setup();
    const { rerender } = renderReader();
    await user.click(screen.getByRole('button', { name: /Next/ }));
    await user.click(screen.getByRole('button', { name: /Next/ }));

    layout.narrow = false;
    rerender(<StoryReader storyId="s1" title="Hurricanes" summary="Where they go" chapters={CHAPTERS} />);
    expect(screen.getByRole('region', { name: 'Chapter 3' })).toHaveAttribute('aria-current', 'step');
    // Chapter 3 starts at 2400 - 100; the next chapter would sit at 3200, 400 px past the line.
    expect(scrolled).toHaveBeenCalledWith({ top: 2300, behavior: 'instant' });
    delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
  });

  it('opens the stepper on the chapter the wide layout was on', async () => {
    layout.narrow = false;
    const { rerender } = renderReader();
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: 1000 });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    const tops = [-500, 300, 1400, 2400];
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: tops[i] }) as DOMRect;
    });
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

    layout.narrow = true;
    rerender(<StoryReader storyId="s1" title="Hurricanes" summary="Where they go" chapters={CHAPTERS} />);
    expect(screen.getByRole('heading', { level: 2, name: 'The coasts' })).toBeInTheDocument();
    expect(pane.resolved?.chapterId).toBe('c2');
  });
});

describe('chapters shrinking under the reader', () => {
  it('clamps to the last chapter left instead of failing', async () => {
    const user = userEvent.setup();
    const { rerender } = renderReader();
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole('button', { name: /Next/ }));
    rerender(<StoryReader storyId="s1" title="Hurricanes" summary={null} chapters={CHAPTERS.slice(0, 2)} />);
    expect(screen.getByRole('heading', { level: 2, name: 'The coasts' })).toBeInTheDocument();
    expect(screen.getByText('2 / 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Previous/ }));
    expect(screen.getByRole('heading', { level: 2, name: 'The tracks' })).toBeInTheDocument();
  });
});


it('shows the cover above the title and serves image blocks from the story', async () => {
  layout.narrow = false;
  const image = {
    id: '00000000-0000-4000-8000-0000000000aa',
    type: 'image' as const,
    v: 1 as const,
    title: null,
    asset_id: '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60',
    config: { alt: 'Storm surge on the coast', caption: null },
  };
  const { container } = render(
    <StoryReader
      storyId="s1"
      coverAssetId="cover-1"
      title="Hurricanes"
      summary={null}
      chapters={[{ ...CHAPTERS[0], blocks: [image] }]}
    />,
  );
  const block = await screen.findByRole('img', { name: 'Storm surge on the coast' });
  expect(block.getAttribute('src')).toMatch(/^blob:/);
  const header = container.querySelector('header')!;
  await waitFor(() => expect(header.querySelector('img[alt=""]')).not.toBeNull());
});

describe('a story with no scenes', () => {
  const TEXT_ONLY = CHAPTERS.map((chapter) => ({ ...chapter, scene: null, scene_hidden: false }));

  it.each([
    ['narrow', true],
    ['wide', false],
  ])('reads as text alone, with no map pane (%s)', (_layout, narrow) => {
    layout.narrow = narrow;
    render(<StoryReader storyId="s1" title="Hurricanes" summary="Where they go" chapters={TEXT_ONLY} />);
    expect(screen.getByRole('heading', { level: 2, name: 'The tracks' })).toBeInTheDocument();
    expect(screen.queryByTestId('story-map')).not.toBeInTheDocument();
  });

  it("keeps the map pane when the only scene is on a map the reader can't open", () => {
    const hidden = TEXT_ONLY.map((chapter, i) => (i === 1 ? { ...chapter, scene_hidden: true } : chapter));
    render(<StoryReader storyId="s1" title="Hurricanes" summary="Where they go" chapters={hidden} />);
    expect(screen.getByTestId('story-map')).toBeInTheDocument();
    expect(pane.hint).toBe("This chapter's map is unavailable or has been deleted.");
  });
});

describe('reader theme', () => {
  const theme = { accent: '#0a7f4f', logo_url: 'https://cdn.example.com/logo.svg', font_family: null };

  it('scopes the accent to the reader and shows the logo', () => {
    const { container } = render(
      <StoryReader storyId="s1" title="Hurricanes" summary={null} chapters={CHAPTERS} readerTheme={theme} />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.style.getPropertyValue('--primary')).toBe('#0a7f4f');
    expect(document.documentElement.style.getPropertyValue('--primary')).toBe('');
    expect(container.querySelector('header img')).toHaveAttribute('src', theme.logo_url);
  });

  it('renders with the standard tokens and no logo without a theme', () => {
    const { container } = renderReader();
    expect((container.firstElementChild as HTMLElement).getAttribute('style')).toBeNull();
    expect(container.querySelector('header img')).toBeNull();
  });
});

const SETTINGS: StorySettings = { navigation: false, layout: 'side', panel_position: 'left', theme: 'follow', transition: 'fly' };

function renderWith(settings: Partial<StorySettings> | null, chapters = CHAPTERS) {
  return render(
    <StoryReader
      storyId="s1"
      title="Hurricanes"
      summary={null}
      chapters={chapters}
      settings={settings && { ...SETTINGS, ...settings }}
    />,
  );
}

describe('navigation bar', () => {
  it.each([[null], [{ navigation: false }]])('is off unless the story turns it on (%j)', (settings) => {
    layout.narrow = false;
    renderWith(settings);
    expect(screen.queryByRole('navigation', { name: 'Story chapters' })).not.toBeInTheDocument();
  });

  it('numbers a chapter whose title is only whitespace', () => {
    layout.narrow = false;
    renderWith({ navigation: true }, [{ ...CHAPTERS[0], title: '   ' }, CHAPTERS[1]]);
    const nav = screen.getByRole('navigation', { name: 'Story chapters' });
    expect(within(nav).getByRole('button', { name: 'Chapter 1' })).toBeInTheDocument();
  });

  it('lists the chapters under the story title, numbering an untitled one', () => {
    layout.narrow = false;
    renderWith({ navigation: true });
    const nav = screen.getByRole('navigation', { name: 'Story chapters' });
    expect(nav).toHaveTextContent('Hurricanes');
    const items = Array.from(nav.querySelectorAll('li')).map((li) => li.textContent);
    expect(items).toEqual(['The tracks', 'The coasts', 'Chapter 3', 'Gone']);
  });

  it('marks the open chapter, follows the stepper and does not announce on its own', async () => {
    const user = userEvent.setup();
    layout.narrow = false;
    renderWith({ navigation: true });
    const nav = screen.getByRole('navigation', { name: 'Story chapters' });
    expect(within(nav).getByRole('button', { name: 'The tracks' })).toHaveAttribute('aria-current', 'step');

    await user.click(within(nav).getByRole('button', { name: 'Chapter 3' }));
    expect(within(nav).getByRole('button', { name: 'Chapter 3' })).toHaveAttribute('aria-current', 'step');
    expect(within(nav).getByRole('button', { name: 'The tracks' })).not.toHaveAttribute('aria-current');
    expect(pane.resolved?.chapterId).toBe('c2');
  });

  it('scrolls the panel to the chosen chapter without handing the scene to the next one', async () => {
    const user = userEvent.setup();
    layout.narrow = false;
    renderWith({ navigation: true });
    const panel = screen.getByRole('region', { name: 'Story chapters', hidden: false });
    const scrollTo = vi.fn();
    panel.scrollTo = scrollTo;
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: 1000 });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    // Chapter 2 sits at 700, and chapter 3 only 100 px below it.
    const tops = [0, 700, 800, 2000];
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: 100 + tops[i] }) as DOMRect;
    });
    await user.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'The coasts' }));
    // 800 - 400 keeps chapter 3's top at the 40% line, not above it.
    expect(scrollTo).toHaveBeenCalledWith({ top: 400, behavior: 'instant' });

    // After that scroll the short chapter is still the open one.
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: 100 + tops[i] - 400 }) as DOMRect;
    });
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');
  });

  it('collapses into a menu on narrow screens that Escape closes', async () => {
    const user = userEvent.setup();
    layout.narrow = true;
    renderWith({ navigation: true });
    const nav = screen.getByRole('navigation', { name: 'Story chapters' });
    const menu = within(nav).getByRole('button', { name: 'Chapters' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(menu);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('list')).toHaveClass('overflow-y-auto', 'min-h-0');
    await user.click(within(dialog).getByRole('button', { name: 'Gone' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('region', { name: 'Gone' })).toBeInTheDocument();

    await user.click(menu);
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(menu).toHaveFocus();
  });
});

describe('floating layout', () => {
  it('keeps the side panel by default', () => {
    layout.narrow = false;
    renderWith({ layout: 'side', panel_position: 'right' });
    expect(screen.getByRole('region', { name: 'Story chapters' })).not.toHaveClass('absolute');
    expect(screen.getByTestId('story-map').parentElement).not.toHaveClass('absolute');
  });

  it('keeps a thin scrollbar visible on the floating panel only', () => {
    layout.narrow = false;
    const { unmount } = renderWith({ layout: 'floating' });
    expect(screen.getByRole('region', { name: 'Story chapters' })).toHaveClass('story-floating-scroll');
    unmount();
    renderWith({ layout: 'side' });
    expect(screen.getByRole('region', { name: 'Story chapters' })).not.toHaveClass('story-floating-scroll');
  });

  it.each([
    ['left', 'left-14'],
    ['right', 'right-14'],
    ['center', 'lg:left-1/2'],
  ] as const)('floats an opaque panel over a full-bleed map at the %s', (position, edge) => {
    layout.narrow = false;
    renderWith({ layout: 'floating', panel_position: position });
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    expect(panel).toHaveClass('absolute', 'bg-card', 'max-w-[calc(100%-24rem)]', edge);
    expect(panel.className).not.toMatch(/bg-card\//);
    expect(screen.getByTestId('story-map').parentElement).toHaveClass('absolute', 'inset-0');
  });

  it('scrolls between chapters inside the floating panel', async () => {
    layout.narrow = false;
    renderWith({ layout: 'floating' });
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: 1000 });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: [-500, 300, 1400, 2400][i] }) as DOMRect;
    });
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(pane.resolved?.chapterId).toBe('c2');
  });

  it.each([
    ['left', 'end'],
    ['center', undefined],
    ['right', undefined],
  ] as const)('keeps the legend off the %s panel', (position, side) => {
    layout.narrow = false;
    renderWith({ layout: 'floating', panel_position: position });
    expect(pane.legendSide).toBe(side);
  });

  it.each(['left', 'center', 'right'] as const)('tells the map about the %s panel', (position) => {
    layout.narrow = false;
    renderWith({ layout: 'floating', panel_position: position });
    expect(pane.panel).toBe(position);
  });

  it('leaves the legend where it is in the side layout', () => {
    layout.narrow = false;
    renderWith({ layout: 'side' });
    expect(pane.legendSide).toBeUndefined();
  });

  it('clears the map for a chapter with no title or text, and brings the panel back after it', async () => {
    const user = userEvent.setup();
    layout.narrow = false;
    Element.prototype.scrollIntoView = vi.fn();
    const blank = { ...CHAPTERS[1], title: null, blocks: [] };
    renderWith({ layout: 'floating', navigation: true }, [CHAPTERS[0], blank, CHAPTERS[2]]);
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    expect(panel).toHaveClass('bg-card');
    expect(panel).not.toHaveClass('pointer-events-none');
    expect(panel).not.toHaveAttribute('inert');
    expect(panel).toHaveAttribute('tabindex', '0');

    await user.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'Chapter 2' }));
    expect(screen.getByRole('region', { name: 'Story chapters' })).toBe(panel);
    expect(panel).toHaveClass('bg-transparent');
    expect(panel).not.toHaveClass('bg-card');
    expect(panel).toHaveClass('pointer-events-none');
    expect(panel).toHaveAttribute('inert');
    expect(panel).not.toHaveAttribute('tabindex');
    // Nothing shows in a bare panel, so no scrollbar may sit over the map either.
    expect(panel).not.toHaveClass('story-floating-scroll');

    // With the panel out of the way, its own buttons advance the story.
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(panel).toHaveClass('bg-card');
    expect(panel).not.toHaveClass('pointer-events-none');
    expect(panel).not.toHaveAttribute('inert');
    expect(panel).toHaveAttribute('tabindex', '0');
    expect(screen.queryByRole('button', { name: /Next/ })).not.toBeInTheDocument();
  });

  it('keeps a short last chapter selected after jumping to it', async () => {
    const user = userEvent.setup();
    layout.narrow = false;
    renderWith({ navigation: true });
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    panel.scrollTo = vi.fn();
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: 1000 });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    // Every chapter starts within the first 40% of the panel, so the jump clamps to the top.
    panel.querySelectorAll('section').forEach((section, i) => {
      section.getBoundingClientRect = () => ({ top: 100 + i * 100 }) as DOMRect;
    });
    await user.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'The coasts' }));
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');

    // The reader's own scroll is measured again.
    panel.scrollTop = 30;
    fireEvent.scroll(panel);
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(screen.getByRole('region', { name: 'Gone' })).toHaveAttribute('aria-current', 'step');
  });

  it('is the stepper on a phone, as in the side layout', () => {
    layout.narrow = true;
    renderWith({ layout: 'floating' });
    expect(screen.getByRole('group', { name: 'Chapters' })).toBeInTheDocument();
    expect(screen.getByTestId('story-map').parentElement).not.toHaveClass('absolute');
  });

  it('keeps the panel mounted on a chapter with no blocks, so scrolling still moves on', async () => {
    const user = userEvent.setup();
    layout.narrow = false;
    Element.prototype.scrollIntoView = vi.fn();
    const chapters = [CHAPTERS[0], { ...CHAPTERS[1], blocks: [] }, CHAPTERS[2]];
    renderWith({ layout: 'floating', navigation: true }, chapters);
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    await user.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'The coasts' }));
    expect(screen.getByRole('region', { name: 'Story chapters' })).toBe(panel);
    expect(within(panel).getByRole('heading', { name: 'The coasts' })).toBeInTheDocument();
    expect(within(panel).queryByText('Second text')).not.toBeInTheDocument();
    expect(screen.getByTestId('story-map')).toBeInTheDocument();
  });
});

describe('chromeless', () => {
  it('links nowhere else in the app but keeps the story and its navigation bar', () => {
    layout.narrow = false;
    render(
      <StoryReader
        chromeless
        storyId="s1"
        title="Hurricanes"
        summary="Where they go"
        chapters={CHAPTERS}
        editHref="/stories/s1/edit"
        headerActions={<button type="button">Embed</button>}
        settings={{ navigation: true, layout: 'side', panel_position: 'right', theme: 'follow', transition: 'fly' }}
      />,
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Embed' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Hurricanes' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Story chapters' })).toBeInTheDocument();
    expect(screen.getByTestId('story-map')).toBeInTheDocument();
  });

  it('is the phone stepper when the frame is narrow', () => {
    render(<StoryReader chromeless storyId="s1" title="Hurricanes" summary={null} chapters={CHAPTERS} editHref="/stories/s1/edit" />);
    expect(screen.getByRole('group', { name: 'Chapters' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Next/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
  });

  describe('links in the story', () => {
    const MAP_URL = `${window.location.origin}/maps/m1`;
    const LINKED: StoryChapter[] = [
      {
        id: 'c1',
        title: 'Linked',
        scene: null,
        scene_hidden: false,
        blocks: [
          markdown('00000000-0000-4000-8000-000000000011', 'See [the other story](/stories/s2) or [jump down](#later).'),
          { id: '00000000-0000-4000-8000-000000000012', type: 'button', v: 1, title: null, config: { label: 'Open the map', url: MAP_URL, new_tab: false } },
        ],
      },
    ];
    let open: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      open = vi.spyOn(window, 'open').mockReturnValue(null);
    });
    afterEach(() => open.mockRestore());

    function click(name: string): boolean {
      const event = new MouseEvent('click', { bubbles: true, cancelable: true });
      screen.getByRole('link', { name }).dispatchEvent(event);
      return event.defaultPrevented;
    }

    it.each([true, false])('open in a new tab in an embed, so the frame stays on the story (narrow: %s)', (narrow) => {
      layout.narrow = narrow;
      render(<StoryReader chromeless storyId="s1" title="Hurricanes" summary={null} chapters={LINKED} />);

      expect(click('the other story')).toBe(true);
      expect(open).toHaveBeenLastCalledWith(`${window.location.origin}/stories/s2`, '_blank', 'noopener,noreferrer');
      expect(click('Open the map')).toBe(true);
      expect(open).toHaveBeenLastCalledWith(MAP_URL, '_blank', 'noopener,noreferrer');

      expect(click('jump down')).toBe(false);
      expect(open).toHaveBeenCalledTimes(2);
    });

    it('follow as written outside an embed', () => {
      render(<StoryReader storyId="s1" title="Hurricanes" summary={null} chapters={LINKED} />);
      expect(click('the other story')).toBe(false);
      expect(click('Open the map')).toBe(false);
      expect(open).not.toHaveBeenCalled();
    });
  });

  it.each([true, false])('puts header actions beside the title and Edit outside an embed (narrow: %s)', (narrow) => {
    layout.narrow = narrow;
    render(
      <StoryReader
        storyId="s1"
        title="Hurricanes"
        summary={null}
        chapters={CHAPTERS}
        editHref="/stories/s1/edit"
        headerActions={<button type="button">Embed</button>}
      />,
    );
    const header = screen.getByRole('heading', { level: 1, name: 'Hurricanes' }).closest('header')!;
    expect(within(header).getByRole('button', { name: 'Embed' })).toBeInTheDocument();
    expect(within(header).getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/stories/s1/edit');
  });
});

it("gives the map the story's default transition", () => {
  const settings = { navigation: false, layout: 'side', panel_position: 'left', theme: 'follow', transition: 'cut' } as const;
  render(<StoryReader storyId="s1" title="Hurricanes" summary={null} chapters={CHAPTERS} settings={settings} />);
  expect(pane.defaultTransition).toBe('cut');
});
