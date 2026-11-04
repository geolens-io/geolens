import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { applyDraftEdit, imagesMissingAlt, type DraftEdit } from '../story-draft';
import { GalleryBlockField } from '../GalleryBlockField';
import { useState } from 'react';
import type { StoryChapter } from '@/types/api';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: async () => new Blob(['x'], { type: 'image/webp' }),
}));

const uploads = { get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false };
const asset = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;

function chapterWith(count: number, extra: Record<string, unknown> = {}): StoryChapter {
  return {
    id: 'c1',
    title: null,
    scene: null,
    scene_hidden: false,
    blocks: [
      {
        id: 'g1',
        type: 'gallery',
        v: 1,
        title: null,
        config: {
          images: Array.from({ length: count }, (_, i) => ({ asset_id: asset(i + 1), alt: `Photo ${i + 1}`, ...extra })),
        },
      },
    ],
  } as StoryChapter;
}

function Harness({ initial, onEdit }: { initial: StoryChapter; onEdit?: (e: DraftEdit) => void }) {
  const [chapters, setChapters] = useState([initial]);
  const block = chapters[0].blocks![0] as Extract<NonNullable<StoryChapter['blocks']>[number], { type: 'gallery' }>;
  return (
    <GalleryBlockField
      storyId="s1"
      uploads={uploads}
      chapterId="c1"
      block={block}
      label="Gallery 1"
      edit={(change) => {
        onEdit?.(change);
        setChapters((current) => applyDraftEdit(current, change));
      }}
    />
  );
}

const order = () => screen.getAllByRole('textbox', { name: /^Alt text for image/ }).map((input) => (input as HTMLInputElement).value);

it('states the cap and reorders images from the keyboard, keeping focus on the moved row', async () => {
  const user = userEvent.setup();
  render(<Harness initial={chapterWith(3)} />);

  expect(screen.getByText('Up to 12 images in this block.')).toBeInTheDocument();
  expect(order()).toEqual(['Photo 1', 'Photo 2', 'Photo 3']);
  expect(screen.getByRole('button', { name: 'Move image 1 up' })).toBeDisabled();

  await user.click(screen.getByRole('button', { name: 'Move image 2 down' }));

  expect(order()).toEqual(['Photo 1', 'Photo 3', 'Photo 2']);
  expect(screen.getByRole('button', { name: 'Move image 3 up' })).toHaveFocus();
});

it('removes an image but keeps the last one', async () => {
  const user = userEvent.setup();
  render(<Harness initial={chapterWith(2)} />);

  await user.click(screen.getByRole('button', { name: 'Remove image 1' }));

  expect(order()).toEqual(['Photo 2']);
  expect(screen.getByRole('button', { name: 'Remove image 1' })).toBeDisabled();
});

it('turns off adding at the cap', () => {
  render(<Harness initial={chapterWith(12)} />);

  expect(screen.getByRole('button', { name: 'Add another image' })).toBeDisabled();
});

it('asks for alt text on each image until it is marked decorative, and counts them for the save gate', async () => {
  const user = userEvent.setup();
  const chapter = chapterWith(2);
  (chapter.blocks![0] as { config: { images: Array<{ alt?: string }> } }).config.images[1].alt = '';
  render(<Harness initial={chapter} />);

  expect(imagesMissingAlt([chapter])).toBe(1);
  expect(screen.getByRole('textbox', { name: 'Alt text for image 2' })).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByRole('textbox', { name: 'Alt text for image 1' })).toHaveAttribute('aria-invalid', 'false');

  await user.click(screen.getByRole('checkbox', { name: 'Image 2 is decorative' }));
  expect(screen.queryByRole('textbox', { name: 'Alt text for image 2' })).not.toBeInTheDocument();
});

it('addresses entries by position when one image appears twice', async () => {
  const user = userEvent.setup();
  const chapter = chapterWith(2);
  const images = (chapter.blocks![0] as { config: { images: Array<{ asset_id: string; caption?: string | null }> } }).config.images;
  images[1].asset_id = images[0].asset_id;
  render(<Harness initial={chapter} />);

  const second = screen.getByRole('textbox', { name: 'Caption for image 2 (optional)' });
  await user.type(second, 'x');
  expect(screen.getByRole('textbox', { name: 'Caption for image 1 (optional)' })).toHaveValue('');
  expect(second).toHaveValue('x');

  await user.click(screen.getByRole('button', { name: 'Remove image 1' }));
  expect(order()).toEqual(['Photo 2']);
});
