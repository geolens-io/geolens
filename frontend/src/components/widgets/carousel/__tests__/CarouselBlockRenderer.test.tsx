import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import CarouselBlockRenderer from '../CarouselBlockRenderer';
import type { GalleryConfig } from '../../gallery/definition';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/webp' })),
}));

const images = [
  { asset_id: '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60', alt: 'First view' },
  { asset_id: '1b2c3d4e-5f60-4a71-8b92-a3b4c5d6e7f8', alt: 'Second view' },
  { asset_id: '2c3d4e5f-6071-4b82-9ca3-b4c5d6e7f809', alt: 'Third view' },
];

function renderCarousel(config: GalleryConfig) {
  return render(
    <CarouselBlockRenderer
      config={config}
      assetPathFor={(assetId: string) => `/stories/s1/assets/${assetId}`}
    />,
  );
}

describe('carousel dots', () => {
  it('select an image and mark the current one', async () => {
    const user = userEvent.setup();
    renderCarousel({ images });
    const dots = screen.getAllByRole('button', { name: /^Image \d of 3$/ });
    expect(dots).toHaveLength(3);
    expect(dots[0].parentElement).toHaveClass('flex-wrap');
    expect(dots[0]).toHaveAttribute('aria-current', 'true');

    await user.click(dots[2]);
    expect(await screen.findByRole('img', { name: 'Third view' })).toBeInTheDocument();
    expect(dots[2]).toHaveAttribute('aria-current', 'true');
    expect(dots[0]).not.toHaveAttribute('aria-current');
  });

  it('are absent for a single image', () => {
    renderCarousel({ images: [images[0]] });
    expect(screen.queryByRole('button', { name: /^Image \d of 1$/ })).not.toBeInTheDocument();
  });
});
