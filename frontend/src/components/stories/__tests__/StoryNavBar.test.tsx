import userEvent from '@testing-library/user-event';
import { act, cleanup, fireEvent, render, screen } from '@/test/test-utils';
import { StoryNavBar } from '../StoryNavBar';
import type { StoryChapter } from '@/types/api';

const chapters = Array.from({ length: 6 }, (_, i) => ({
  id: `c${i}`,
  title: `Chapter ${i + 1}`,
  scene: null,
  scene_hidden: false,
  blocks: [],
})) as unknown as StoryChapter[];

describe('StoryNavBar', () => {
  const scrollIntoView = vi.fn();
  beforeEach(() => {
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  it('scrolls the open chapter into view when it changes', () => {
    const props = { title: 'Story', chapters, onSelect: vi.fn(), collapsed: false };
    const { rerender } = render(<StoryNavBar {...props} active={0} />);
    scrollIntoView.mockClear();
    rerender(<StoryNavBar {...props} active={5} />);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByRole('button', { name: 'Chapter 6' }));
  });

  it('shows the end fade when a tab grows past the list without the list resizing', () => {
    const observed: Element[] = [];
    let notify = () => {};
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: () => void) {
          notify = callback;
        }
        observe(element: Element) {
          observed.push(element);
        }
        disconnect() {}
      },
    );
    const widths = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(300);
    const client = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
    try {
      const { rerender } = render(
        <StoryNavBar title="Story" chapters={chapters} active={0} onSelect={vi.fn()} collapsed={false} />,
      );
      const list = screen.getByRole('list');
      expect(list.className).not.toContain('mask-image');
      // A web font lands: a tab widens, the list keeps its box.
      widths.mockReturnValue(900);
      expect(observed).toContain(list.querySelector('li'));
      act(() => notify());
      expect(list).toHaveClass('[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]');

      // Replacement chapters with the same count get their new tabs observed.
      const renamed = chapters.map((chapter) => ({ ...chapter, id: `${chapter.id}-b` }));
      rerender(<StoryNavBar title="Story" chapters={renamed} active={0} onSelect={vi.fn()} collapsed={false} />);
      expect(observed).toContain(list.querySelector('li'));
    } finally {
      widths.mockRestore();
      client.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it('fades only the side with tabs hidden past it, and not the menu list', async () => {
    const props = { title: 'Story', chapters, active: 0, onSelect: vi.fn() };
    const widths = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(900);
    const client = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
    const { unmount } = render(<StoryNavBar {...props} collapsed={false} />);
    const list = screen.getByRole('list');
    expect(list).toHaveClass('overflow-x-auto', '[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]');

    list.scrollLeft = 300;
    fireEvent.scroll(list);
    expect(list).toHaveClass('[mask-image:linear-gradient(to_right,transparent,black_2rem,black_calc(100%-2rem),transparent)]');

    list.scrollLeft = 600;
    fireEvent.scroll(list);
    expect(list).toHaveClass('[mask-image:linear-gradient(to_right,transparent,black_2rem)]');
    unmount();

    client.mockReturnValue(900);
    render(<StoryNavBar {...props} collapsed={false} />);
    expect(screen.getByRole('list').className).not.toContain('mask-image');
    widths.mockRestore();
    client.mockRestore();
    cleanup();

    render(<StoryNavBar {...props} collapsed />);
    await userEvent.setup().click(screen.getByRole('button', { name: /chapters/i }));
    expect(screen.getByRole('list').className).not.toContain('mask-image');
  });
});
