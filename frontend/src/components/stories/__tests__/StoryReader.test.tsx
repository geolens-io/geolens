import userEvent from '@testing-library/user-event';
import { act, render, screen } from '@/test/test-utils';
import { StoryReader } from '../StoryReader';
import type { ResolvedScene } from '../story-scenes';
import type { StoryChapter, StoryScene } from '@/types/api';

const layout = vi.hoisted(() => ({ narrow: true }));
const pane = vi.hoisted(() => ({ resolved: null as ResolvedScene | null, hint: undefined as string | undefined }));

const prefetch = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => layout.narrow }));
vi.mock('@/hooks/use-maps', () => ({ prefetchMap: (_qc: unknown, id: string) => prefetch(id) }));
vi.mock('../StoryMapPane', () => ({
  StoryMapPane: ({ resolved, emptyHint }: { resolved: ResolvedScene | null; emptyHint?: string }) => {
    pane.resolved = resolved;
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
  return render(<StoryReader title="Hurricanes" summary="Where they go" chapters={CHAPTERS} />);
}

beforeEach(() => {
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
  type Observed = { callback: IntersectionObserverCallback; options?: IntersectionObserverInit; targets: Element[] };
  let observers: Observed[];

  beforeEach(() => {
    observers = [];
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        record: Observed;
        constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
          this.record = { callback, options, targets: [] };
          observers.push(this.record);
        }
        observe(target: Element) {
          this.record.targets.push(target);
        }
        disconnect() {}
      },
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  // A 1000 px panel at y = 100, so the 40% line sits at y = 500.
  function report(observer: Observed, tops: number[], reported: number[] = tops.map((_, i) => i)) {
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    Object.defineProperty(panel, 'clientHeight', { configurable: true, value: 1000 });
    panel.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
    observer.targets.forEach((target, i) => {
      target.getBoundingClientRect = () => ({ top: tops[i] }) as DOMRect;
    });
    const entries = reported.map((i) => ({ target: observer.targets[i] }));
    act(() => observer.callback(entries as unknown as IntersectionObserverEntry[], {} as IntersectionObserver));
  }

  it('makes the chapter whose top has crossed 40% of the panel active', () => {
    layout.narrow = false;
    renderReader();
    const panel = screen.getByRole('region', { name: 'Story chapters' });
    const observer = observers.at(-1)!;
    expect(observer.options?.root).toBe(panel);
    expect(observer.options?.rootMargin).toBe('0px 0px -60% 0px');
    expect(observer.targets).toHaveLength(4);
    expect(pane.resolved?.chapterId).toBe('c1');

    report(observer, [-500, 300, 1400, 2400]);
    expect(pane.resolved?.chapterId).toBe('c2');
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');

    report(observer, [-500, 550, 1650, 2650]);
    expect(pane.resolved?.chapterId).toBe('c1');
  });

  it('measures every chapter again when a jump reports only one of them', () => {
    layout.narrow = false;
    renderReader();
    const observer = observers.at(-1)!;
    report(observer, [-3000, -2000, -1000, 200]);
    expect(screen.getByRole('region', { name: 'Gone' })).toHaveAttribute('aria-current', 'step');

    // Home: only the first chapter's intersection changed, but all moved below the line.
    report(observer, [150, 900, 1800, 2700], [0]);
    expect(screen.getByRole('region', { name: 'The tracks' })).toHaveAttribute('aria-current', 'step');
    expect(pane.resolved?.chapterId).toBe('c1');
  });

  it("doesn't announce the opening chapter when the observer first reports", async () => {
    layout.narrow = false;
    renderReader();
    report(observers.at(-1)!, [140, 900, 1800, 2700]);
    await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('stays on the open chapter, or the nearest one, when a refetch changes the chapters', () => {
    layout.narrow = false;
    const { rerender } = renderReader();
    const observer = observers.at(-1)!;
    report(observer, [-500, 300, 1400, 2400]);
    rerender(<StoryReader title="Hurricanes" summary={null} chapters={[CHAPTERS[1], CHAPTERS[0]]} />);
    expect(screen.getByRole('region', { name: 'The coasts' })).toHaveAttribute('aria-current', 'step');
  });
});

describe('chapters shrinking under the reader', () => {
  it('clamps to the last chapter left instead of failing', async () => {
    const user = userEvent.setup();
    const { rerender } = renderReader();
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole('button', { name: /Next/ }));
    rerender(<StoryReader title="Hurricanes" summary={null} chapters={CHAPTERS.slice(0, 2)} />);
    expect(screen.getByRole('heading', { level: 2, name: 'The coasts' })).toBeInTheDocument();
    expect(screen.getByText('2 / 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Previous/ }));
    expect(screen.getByRole('heading', { level: 2, name: 'The tracks' })).toBeInTheDocument();
  });
});
