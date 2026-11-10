import { useState } from 'react';
import { toast } from 'sonner';
import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { ChapterEditor } from '../ChapterEditor';
import { applyDraftEdit } from '../story-draft';
import type { StoryChapter } from '@/types/api';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

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
      uploads={{ get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false }}
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

it('moves blocks with per-kind names and disables the arrows at the ends', async () => {
  const edit = vi.fn();
  render(
    <ChapterEditor
      storyId="s1"
      uploads={{ get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false }}
      chapter={CHAPTER}
      index={0}
      edit={edit}
      readView={() => null}
      mapMissing={false}
      focusTitle={false}
    />,
  );

  expect(screen.getByRole('button', { name: 'Move text block 1 up' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Move text block 2 down' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Move image 1 up' })).toBeEnabled();

  await userEvent.setup().click(screen.getByRole('button', { name: 'Move image 1 down' }));
  expect(edit).toHaveBeenCalledWith({
    type: 'moveBlock',
    chapterId: 'c1',
    blockId: '00000000-0000-4000-8000-000000000002',
    by: 1,
  });
});

function editorWith(chapter: StoryChapter, edit = vi.fn()) {
  render(
    <ChapterEditor
      storyId="s1"
      uploads={{ get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false }}
      chapter={chapter}
      index={0}
      edit={edit}
      readView={() => null}
      mapMissing={false}
      focusTitle={false}
    />,
  );
  return edit;
}

it('adds a button and a separator', async () => {
  const edit = editorWith({ ...CHAPTER, blocks: [] } as StoryChapter);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Add button' }));
  await user.click(screen.getByRole('button', { name: 'Add separator' }));
  expect(edit).toHaveBeenNthCalledWith(1, { type: 'addButtonBlock', chapterId: 'c1', blockId: expect.any(String) });
  expect(edit).toHaveBeenNthCalledWith(2, { type: 'addSeparatorBlock', chapterId: 'c1', blockId: expect.any(String) });
});

it('edits, moves and removes button and separator blocks', async () => {
  const buttonId = '00000000-0000-4000-8000-0000000000b1';
  const separatorId = '00000000-0000-4000-8000-0000000000b2';
  const edit = editorWith({
    ...CHAPTER,
    blocks: [
      { id: buttonId, type: 'button', v: 1, title: null, config: { label: 'Go', url: 'https://example.com', new_tab: false } },
      { id: separatorId, type: 'separator', v: 1, title: null, config: { style: 'line' } },
    ],
  } as StoryChapter);
  const user = userEvent.setup();

  expect(screen.getByRole('group', { name: 'Button 1' })).toBeInTheDocument();
  expect(screen.getByRole('group', { name: 'Separator 1' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Move button 1 up' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Move separator 1 down' })).toBeDisabled();

  await user.type(screen.getByLabelText('Button label'), '!');
  expect(edit).toHaveBeenLastCalledWith({ type: 'setButton', chapterId: 'c1', blockId: buttonId, label: 'Go!' });
  await user.click(screen.getByRole('checkbox', { name: 'Open in a new tab' }));
  expect(edit).toHaveBeenLastCalledWith({ type: 'setButton', chapterId: 'c1', blockId: buttonId, newTab: true });
  await user.click(screen.getByRole('radio', { name: 'Gap' }));
  expect(edit).toHaveBeenLastCalledWith({ type: 'setSeparator', chapterId: 'c1', blockId: separatorId, style: 'gap' });

  await user.click(screen.getByRole('button', { name: 'Move button 1 down' }));
  expect(edit).toHaveBeenLastCalledWith({ type: 'moveBlock', chapterId: 'c1', blockId: buttonId, by: 1 });
  await user.click(screen.getByRole('button', { name: 'Remove separator 1' }));
  expect(edit).toHaveBeenLastCalledWith({ type: 'removeBlock', chapterId: 'c1', blockId: separatorId });
});

it('flags a button with a script address', () => {
  editorWith({
    ...CHAPTER,
    blocks: [
      { id: 'b', type: 'button', v: 1, title: null, config: { label: 'Go', url: 'javascript:alert(1)', new_tab: false } },
    ],
  } as StoryChapter);
  expect(screen.getByLabelText('Link address')).toBeInvalid();
  expect(screen.getByText('Enter an address that starts with http:// or https://.')).toBeInTheDocument();
});

it('keeps focus on a moved gallery block’s own arrow, not on an arrow of one of its images', async () => {
  const gallery = {
    id: '00000000-0000-4000-8000-000000000010',
    type: 'gallery' as const,
    v: 1 as const,
    title: null,
    config: {
      images: [
        { asset_id: '00000000-0000-4000-8000-000000000011', alt: 'One' },
        { asset_id: '00000000-0000-4000-8000-000000000012', alt: 'Two' },
      ],
    },
  };
  function Harness() {
    const [chapter, setChapter] = useState({
      ...CHAPTER,
      blocks: [gallery, markdown('00000000-0000-4000-8000-000000000013')],
    } as StoryChapter);
    return (
      <ChapterEditor
        storyId="s1"
        uploads={{ get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false }}
        chapter={chapter}
        index={0}
        edit={(change) => setChapter(applyDraftEdit([chapter], change)[0])}
        readView={() => null}
        mapMissing={false}
        focusTitle={false}
      />
    );
  }
  render(<Harness />);

  await userEvent.setup().click(screen.getByRole('button', { name: 'Move gallery 1 down' }));

  expect(screen.getByRole('button', { name: 'Move gallery 1 up' })).toHaveFocus();
});

it('reports a gallery upload that finishes after the chapter filled up, and adds nothing', async () => {
  const edit = vi.fn();
  const start = vi.fn();
  const props = {
    storyId: 's1',
    uploads: { get: () => ({ progress: null, error: null }), start, cancelAll: vi.fn(), uploading: false },
    index: 0,
    edit,
    readView: () => null,
    mapMissing: false,
    focusTitle: false,
  };
  const blocks = (count: number) =>
    Array.from({ length: count }, (_, i) => markdown(`00000000-0000-4000-8000-${String(i).padStart(12, '0')}`));
  const { rerender } = render(<ChapterEditor {...props} chapter={{ ...CHAPTER, blocks: blocks(99) } as StoryChapter} />);

  await userEvent.setup().upload(screen.getByTestId('story-gallery-input'), new File(['x'], 'a.png', { type: 'image/png' }));
  const finish = start.mock.calls[0][2] as (asset: { id: string }) => void;
  rerender(<ChapterEditor {...props} chapter={{ ...CHAPTER, blocks: blocks(100) } as StoryChapter} />);
  finish({ id: '00000000-0000-4000-8000-0000000000ff' });

  expect(edit).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('A chapter can have up to 100 text blocks.');
});
