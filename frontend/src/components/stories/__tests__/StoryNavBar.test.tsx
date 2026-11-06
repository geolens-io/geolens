import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
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

  it('fades the inline list at its end edge but not the menu list', async () => {
    const props = { title: 'Story', chapters, active: 0, onSelect: vi.fn() };
    const { unmount } = render(<StoryNavBar {...props} collapsed={false} />);
    expect(screen.getByRole('list')).toHaveClass('overflow-x-auto', '[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]');
    unmount();

    render(<StoryNavBar {...props} collapsed />);
    await userEvent.setup().click(screen.getByRole('button', { name: /chapters/i }));
    expect(screen.getByRole('list').className).not.toContain('mask-image');
  });
});
