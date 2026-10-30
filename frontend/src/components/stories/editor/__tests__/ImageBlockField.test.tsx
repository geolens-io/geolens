import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { ImageBlockField } from '../ImageBlockField';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: async () => new Blob(['x'], { type: 'image/webp' }),
}));

const uploads = { get: () => ({ progress: null, error: null }), start: vi.fn(), uploading: false };

function renderField(config: { alt?: string; decorative?: boolean; caption?: string | null }) {
  const edit = vi.fn();
  const block = {
    id: 'img',
    type: 'image' as const,
    v: 1 as const,
    title: null,
    asset_id: '00000000-0000-4000-8000-0000000000aa',
    config,
  };
  render(<ImageBlockField storyId="s1" uploads={uploads} chapterId="c1" block={block} label="Image 1" edit={edit} />);
  return edit;
}

it('asks for alt text until the image is marked decorative', async () => {
  const edit = renderField({ alt: '', caption: null });

  expect(screen.getByRole('textbox', { name: 'Alt text' })).toHaveAttribute('aria-invalid', 'true');
  await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Decorative image' }));

  expect(edit).toHaveBeenCalledWith({ type: 'setImage', chapterId: 'c1', blockId: 'img', decorative: true });
});

it('hides the alt text field of a decorative image', () => {
  renderField({ decorative: true, caption: null });

  expect(screen.getByRole('checkbox', { name: 'Decorative image' })).toBeChecked();
  expect(screen.queryByRole('textbox', { name: 'Alt text' })).not.toBeInTheDocument();
  expect(screen.queryByText('Write alt text before saving.')).not.toBeInTheDocument();
});
