import userEvent from '@testing-library/user-event';
import { act, render, screen, waitFor } from '@/test/test-utils';
import { apiFetchBlob } from '@/api/client';
import { parseStoredWidget } from '../registry';
import { WidgetView } from '../WidgetView';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/webp' })),
}));

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const assets = [
  '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60',
  '1b2c3d4e-5f60-4a71-8b92-a3b4c5d6e7f8',
  '2c3d4e5f-6071-4b82-9ca3-b4c5d6e7f809',
];
const images = [
  { asset_id: assets[0], alt: 'A river', caption: 'Looking north' },
  { asset_id: assets[1], alt: 'A bridge' },
  { asset_id: assets[2], decorative: true },
];

function block(type: 'gallery' | 'carousel', list: unknown[] = images) {
  return { id, type, v: 1, config: { images: list } };
}

function renderBlock(raw: unknown) {
  return render(
    <WidgetView parsed={parseStoredWidget(raw, 'story')} assetPathFor={(asset) => `/stories/s1/assets/${asset}`} />,
  );
}

describe.each(['gallery', 'carousel'] as const)('%s block instances', (type) => {
  it('hold one to twelve images, each with alt text or marked decorative', () => {
    expect(parseStoredWidget(block(type), 'story').ok).toBe(true);
    const many = Array.from({ length: 12 }, (_, i) => ({ asset_id: assets[0], alt: `Photo ${i}` }));
    expect(parseStoredWidget(block(type, many), 'story').ok).toBe(true);
    for (const list of [
      [],
      [...many, { asset_id: assets[1], alt: 'one too many' }],
      [{ asset_id: assets[0] }],
      [{ asset_id: assets[0], alt: ' ' }],
      [{ alt: 'no asset' }],
      [{ asset_id: 'https://example.com/a.png', alt: 'x' }],
      [{ asset_id: assets[0], alt: 'x', url: 'https://example.com/a.png' }],
    ]) {
      expect(parseStoredWidget(block(type, list), 'story').ok, JSON.stringify(list)).toBe(false);
    }
  });

  it('are not dashboard widgets', () => {
    expect(parseStoredWidget(block(type), 'dashboard')).toMatchObject({ ok: false });
  });
});

describe('gallery block renderer', () => {
  it('shows every image with its alt text and caption, and none for a decorative one', async () => {
    renderBlock(block('gallery'));

    expect(await screen.findByRole('img', { name: 'A river' })).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: 'A bridge' })).toBeInTheDocument();
    expect(screen.getByText('Looking north')).toBeInTheDocument();
    expect(screen.getAllByRole('figure')).toHaveLength(3);
    expect(vi.mocked(apiFetchBlob).mock.calls.map((call) => call[0])).toEqual(
      expect.arrayContaining(assets.map((asset) => `/stories/s1/assets/${asset}`)),
    );
  });
});

describe('carousel block renderer', () => {
  it('shows one image at a time with a position that follows the buttons', async () => {
    const user = userEvent.setup();
    renderBlock(block('carousel'));

    const carousel = await screen.findByRole('group', { name: 'Carousel' });
    expect(carousel).toHaveAttribute('aria-roledescription', 'carousel');
    expect(await screen.findByRole('img', { name: 'A river' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'A bridge' })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Image 1 of 3. A river');

    await user.click(screen.getByRole('button', { name: 'Next image' }));
    expect(await screen.findByRole('img', { name: 'A bridge' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Image 2 of 3. A bridge');

    await user.click(screen.getByRole('button', { name: 'Previous image' }));
    expect(await screen.findByRole('img', { name: 'A river' })).toBeInTheDocument();
  });

  it('moves with the arrow keys and wraps at the ends', async () => {
    const user = userEvent.setup();
    renderBlock(block('carousel'));
    await screen.findByRole('img', { name: 'A river' });

    screen.getByRole('button', { name: 'Next image' }).focus();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('status')).toHaveTextContent('Image 3 of 3');
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('Image 1 of 3. A river');
  });

  it('never advances on its own', async () => {
    vi.useFakeTimers();
    try {
      renderBlock(block('carousel'));
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.getByRole('status')).toHaveTextContent('Image 1 of 3');
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows no controls for a single image', async () => {
    renderBlock(block('carousel', [images[0]]));

    expect(await screen.findByRole('img', { name: 'A river' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next image' })).not.toBeInTheDocument();
  });

  it('plays its slide change only when the reader allows motion', async () => {
    renderBlock(block('carousel'));

    const slide = await screen.findByRole('group', { name: 'Image 1 of 3' });
    expect(slide).toHaveAttribute('aria-roledescription', 'slide');
    expect(slide.className).toContain('motion-safe:animate-in');
    expect(slide.className).not.toMatch(/(^|\s)animate-in/);
  });
});

describe('gallery entries that repeat an image', () => {
  const entry = (asset: string, caption: string) => ({ asset_id: asset, alt: caption, caption });
  const view = (list: unknown[]) => (
    <WidgetView
      parsed={parseStoredWidget(block('gallery', list), 'story')}
      assetPathFor={(asset) => `/stories/s1/assets/${asset}`}
    />
  );

  it('keep one figure per entry, in order, when the list is reordered', async () => {
    const a1 = entry(assets[0], 'first');
    const a2 = entry(assets[0], 'second');
    const b = entry(assets[1], 'third');
    const { rerender } = render(view([a1, a2, b]));
    await screen.findAllByRole('figure');
    await waitFor(() => expect(screen.getAllByRole('figure')).toHaveLength(3));

    rerender(view([b, a1, a2]));

    const captions = () => screen.getAllByRole('figure').map((figure) => figure.querySelector('figcaption')?.textContent);
    await waitFor(() => expect(captions()).toEqual(['third', 'first', 'second']));
  });
});

describe('carousel loading and keys', () => {
  const observers: { callback: IntersectionObserverCallback; targets: Element[] }[] = [];

  beforeEach(() => {
    observers.length = 0;
    vi.mocked(apiFetchBlob).mockClear();
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        targets: Element[] = [];
        constructor(callback: IntersectionObserverCallback) {
          observers.push({ callback, targets: this.targets });
        }
        observe(target: Element) {
          this.targets.push(target);
        }
        disconnect() {}
        unobserve() {}
        takeRecords() {
          return [];
        }
      },
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it('waits to fetch the first image until the carousel nears the viewport', async () => {
    renderBlock(block('carousel'));
    await waitFor(() => expect(observers.some((o) => o.targets.length > 0)).toBe(true));
    expect(apiFetchBlob).not.toHaveBeenCalled();

    const { callback, targets } = observers.find((o) => o.targets.length > 0)!;
    act(() =>
      callback([{ isIntersecting: true, target: targets[0] } as IntersectionObserverEntry], {} as IntersectionObserver),
    );

    expect(await screen.findByRole('img', { name: 'A river' })).toBeInTheDocument();
    expect(vi.mocked(apiFetchBlob).mock.calls.map((call) => call[0])).toEqual([`/stories/s1/assets/${assets[0]}`]);
  });

  it('leaves the slide alone for an arrow key with a modifier, and still moves on a plain one', async () => {
    const user = userEvent.setup();
    renderBlock(block('carousel'));
    await screen.findByRole('status');
    screen.getByRole('button', { name: 'Next image' }).focus();

    await user.keyboard('{Alt>}{ArrowRight}{/Alt}');
    expect(screen.getByRole('status')).toHaveTextContent('Image 1 of 3');
    const plain = new KeyboardEvent('keydown', { key: 'ArrowRight', altKey: true, bubbles: true, cancelable: true });
    act(() => {
      screen.getByRole('button', { name: 'Next image' }).dispatchEvent(plain);
    });
    expect(plain.defaultPrevented).toBe(false);

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('Image 2 of 3');
  });
});
