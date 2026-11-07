import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@/test/test-utils';
import { apiFetchBlob } from '@/api/client';
import GalleryBlockRenderer from '../GalleryBlockRenderer';
import type { GalleryConfig } from '../definition';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/webp' })),
}));

const ids = [
  '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60',
  '1b2c3d4e-5f60-4a71-8b92-a3b4c5d6e7f8',
  '2c3d4e5f-6071-4b82-9ca3-b4c5d6e7f809',
];
const images = [
  { asset_id: ids[0], alt: 'First view' },
  { asset_id: ids[1], alt: 'Second view', caption: 'Looking east' },
  { asset_id: ids[2], alt: 'Third view' },
];

function renderGallery(config: GalleryConfig) {
  return render(
    <GalleryBlockRenderer
      config={config}
      assetPathFor={(assetId: string) => `/stories/s1/assets/${assetId}`}
    />,
  );
}

describe('gallery block lightbox', () => {
  it('opens the clicked thumbnail’s image, steps with Next and closes on Escape', async () => {
    const user = userEvent.setup();
    renderGallery({ images });
    const thumb = await screen.findByRole('img', { name: 'Second view' });
    const thumbSrc = thumb.getAttribute('src');
    await user.click(screen.getByRole('button', { name: 'Open image 2 of 3' }));

    const dialog = await screen.findByRole('dialog', { name: 'Looking east' });
    const shown = await within(dialog).findByRole('img', { name: 'Second view' });
    expect(shown.getAttribute('src')).toBe(thumbSrc);
    expect(within(dialog).getByText('Looking east', { selector: 'p' })).toBeInTheDocument();
    // The whole dialog, not only the image, stays inside a short screen.
    expect(dialog).toHaveClass('max-h-[95vh]', 'overflow-y-auto');

    await user.click(within(dialog).getByRole('button', { name: 'Next image' }));
    expect(await within(dialog).findByRole('img', { name: 'Third view' })).toBeInTheDocument();
    expect(within(dialog).getByText('Image 3 of 3')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(vi.mocked(apiFetchBlob)).toHaveBeenCalled();
  });

  it('offers no Previous or Next for a single image', async () => {
    const user = userEvent.setup();
    renderGallery({ images: [images[0]] });
    await user.click(screen.getByRole('button', { name: 'Open image 1 of 1' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByRole('button', { name: 'Next image' })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Previous image' })).not.toBeInTheDocument();
  });
});
