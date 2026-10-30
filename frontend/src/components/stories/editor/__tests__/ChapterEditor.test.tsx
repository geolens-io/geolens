import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { ChapterEditor } from '../ChapterEditor';
import type { StoryChapter } from '@/types/api';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: async () => new Blob(['x'], { type: 'image/webp' }),
}));

function markdown(id: string) {
  return { id, type: 'markdown' as const, v: 1 as const, title: null, config: { text: '' } };
}

function image(id: string) {
  return {
    id,
    type: 'image' as const,
    v: 1 as const,
    title: null,
    asset_id: '00000000-0000-4000-8000-0000000000aa',
    config: { alt: 'A river', caption: null },
  };
}

const CHAPTER = {
  id: 'c1',
  title: 'Rivers',
  scene: null,
  scene_hidden: false,
  blocks: [
    markdown('00000000-0000-4000-8000-000000000001'),
    image('00000000-0000-4000-8000-000000000002'),
    markdown('00000000-0000-4000-8000-000000000003'),
  ],
} as StoryChapter;

it('numbers text blocks and images separately, Remove buttons included', async () => {
  const edit = vi.fn();
  render(
    <ChapterEditor
      storyId="s1"
      chapter={CHAPTER}
      index={0}
      edit={edit}
      readView={() => null}
      mapMissing={false}
      focusTitle={false}
    />,
  );

  expect(screen.getByRole('group', { name: 'Image 1' })).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Text block 2' })).toBeInTheDocument();
  expect(screen.queryByRole('textbox', { name: 'Text block 3' })).not.toBeInTheDocument();
  expect(
    screen.getAllByRole('button', { name: /^Remove / }).map((button) => button.textContent),
  ).toEqual(['Remove text block 1', 'Remove image 1', 'Remove text block 2']);

  await userEvent.setup().click(screen.getByRole('button', { name: 'Remove text block 2' }));
  expect(edit).toHaveBeenCalledWith({
    type: 'removeBlock',
    chapterId: 'c1',
    blockId: '00000000-0000-4000-8000-000000000003',
  });
});
