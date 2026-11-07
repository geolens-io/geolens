import userEvent from '@testing-library/user-event';
import { render, screen, within, fireEvent } from '@/test/test-utils';
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
    // The dialog is 95vw at most with 1.5rem of padding a side, so the image fits inside it on a phone.
    expect(shown).toHaveClass('max-w-[calc(95vw-3rem)]');
    expect(within(dialog).getByText('Looking east', { selector: 'p' })).toBeInTheDocument();
    // The whole dialog, not only the image, stays inside a short screen.
    expect(dialog).toHaveClass('max-h-[95vh]', 'overflow-y-auto');
    // The image starts below the close control rather than running behind it.
    expect(dialog).toHaveClass('pt-10');

    await user.click(within(dialog).getByRole('button', { name: 'Next image' }));
    expect(await within(dialog).findByRole('img', { name: 'Third view' })).toBeInTheDocument();
    expect(within(dialog).getByText('Image 3 of 3')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(vi.mocked(apiFetchBlob)).toHaveBeenCalled();
  });

  it('keeps the open image inside a gallery that a refresh shortened', async () => {
    const user = userEvent.setup();
    const { rerender } = renderGallery({ images });
    await screen.findByRole('img', { name: 'Third view' });
    await user.click(screen.getByRole('button', { name: 'Open image 3 of 3' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Image 3 of 3')).toBeInTheDocument();

    rerender(
      <GalleryBlockRenderer config={{ images: images.slice(0, 2) }} assetPathFor={(assetId: string) => `/stories/s1/assets/${assetId}`} />,
    );
    expect(within(dialog).getByText('Image 2 of 2')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Next image' }));
    expect(within(dialog).getByText('Image 1 of 2')).toBeInTheDocument();
  });

  it('steps images with the arrow keys and keeps them from the story behind the dialog', async () => {
    const user = userEvent.setup();
    const outside = vi.fn();
    render(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a keydown spy standing in for the story stepper
      <div onKeyDown={outside}>
        <GalleryBlockRenderer config={{ images }} assetPathFor={(assetId: string) => `/stories/s1/assets/${assetId}`} />
      </div>,
    );
    await screen.findByRole('img', { name: 'Second view' });
    await user.click(screen.getByRole('button', { name: 'Open image 1 of 3' }));
    const dialog = await screen.findByRole('dialog');
    await user.keyboard('{ArrowRight}');
    expect(within(dialog).getByText('Image 2 of 3')).toBeInTheDocument();
    await user.keyboard('{ArrowLeft}');
    expect(within(dialog).getByText('Image 1 of 3')).toBeInTheDocument();
    expect(outside).not.toHaveBeenCalled();

    // A modified arrow is the browser's (Alt+Left goes back), so it passes untouched.
    for (const modifier of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey'] as const) {
      expect(fireEvent.keyDown(dialog, { key: 'ArrowRight', [modifier]: true })).toBe(true);
      expect(within(dialog).getByText('Image 1 of 3')).toBeInTheDocument();
    }
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
