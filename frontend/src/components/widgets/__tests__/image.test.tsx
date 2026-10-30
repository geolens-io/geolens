import { act, render, screen, waitFor } from '@/test/test-utils';
import { apiFetchBlob, ApiError } from '@/api/client';
import { imageWidget } from '../image/definition';
import { parseStoredWidget, checkWidgetWrite } from '../registry';
import { AssetImage } from '../image/AssetImage';
import { WidgetView } from '../WidgetView';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(),
}));

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const assetId = '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60';
const block = { id, type: 'image', v: 1, asset_id: assetId, config: { alt: 'A river at dusk', caption: 'Looking north' } };

function renderBlock(raw: unknown, assetPath: string | null = `/stories/s1/assets/${assetId}`) {
  return render(<WidgetView parsed={parseStoredWidget(raw, 'story')} assetPath={assetPath ?? undefined} />);
}

describe('image block instances', () => {
  it('keep the image they name through a read, so an edit saves it back', () => {
    const parsed = parseStoredWidget(block, 'story');
    expect(parsed).toMatchObject({ ok: true, instance: { asset_id: assetId, config: block.config } });
    expect(checkWidgetWrite(block, 'story')).toEqual({ ok: true });
  });

  it('need an image and alt text, as the server does', () => {
    const { asset_id: _asset, ...unnamed } = block;
    for (const raw of [
      unnamed,
      { ...block, asset_id: 'https://example.com/a.png' },
      { ...block, config: { alt: '   ' } },
      { ...block, config: { caption: 'x' } },
      { ...block, config: { alt: 'x', url: 'https://example.com/a.png' } },
      { ...block, config: { alt: 'x'.repeat(501) } },
    ]) {
      expect(parseStoredWidget(raw, 'story').ok, JSON.stringify(raw)).toBe(false);
    }
    expect(imageWidget.parseConfig({ alt: 'x', caption: null }, 1)).toEqual({ alt: 'x' });
  });

  it('are not dashboard widgets', () => {
    expect(parseStoredWidget({ ...block, layer_id: assetId }, 'dashboard')).toMatchObject({ ok: false });
  });
});

describe('image block renderer', () => {
  it('shows the image from the host route with its alt text and the caption', async () => {
    vi.mocked(apiFetchBlob).mockImplementation(async () => new Blob(['x'], { type: 'image/webp' }));
    renderBlock(block);
    const image = await screen.findByRole('img', { name: 'A river at dusk' });
    expect(image.tagName).toBe('IMG');
    expect(image.getAttribute('src')).toMatch(/^blob:/);
    expect(vi.mocked(apiFetchBlob).mock.lastCall?.[0]).toBe(`/stories/s1/assets/${assetId}`);
    expect(vi.mocked(apiFetchBlob).mock.lastCall?.[1]?.signal).toBeInstanceOf(AbortSignal);
    expect(screen.getByText('Looking north')).toBeInTheDocument();
  });

  it('falls back to its alt text when the image is missing or not the reader’s', async () => {
    vi.mocked(apiFetchBlob).mockImplementation(async () => {
      throw new ApiError('Not found', 404);
    });
    renderBlock(block);
    expect(await screen.findByText('Image: A river at dusk')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('img', { name: /A river at dusk/ })).not.toBeInTheDocument());
  });

  it('fetches nothing without a host route', async () => {
    let fetched = false;
    vi.mocked(apiFetchBlob).mockImplementation(async () => {
      fetched = true;
      return new Blob();
    });
    renderBlock(block, null);
    expect(await screen.findByText('Image: A river at dusk')).toBeInTheDocument();
    expect(fetched).toBe(false);
  });
});


describe('image block loading', () => {
  const observers: { callback: IntersectionObserverCallback; targets: Element[] }[] = [];

  beforeEach(() => {
    observers.length = 0;
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

  it('waits to fetch an offscreen image until it nears the viewport', async () => {
    const paths: string[] = [];
    vi.mocked(apiFetchBlob).mockImplementation(async (path: string) => {
      paths.push(path);
      return new Blob(['x'], { type: 'image/webp' });
    });
    renderBlock(block);
    expect(await screen.findByRole('img', { name: 'Loading image: A river at dusk' })).toBeInTheDocument();
    await waitFor(() => expect(observers.some((o) => o.targets.length > 0)).toBe(true));
    expect(paths).toEqual([]);

    const { callback, targets } = observers.find((o) => o.targets.length > 0)!;
    act(() =>
      callback([{ isIntersecting: true, target: targets[0] } as IntersectionObserverEntry], {} as IntersectionObserver),
    );
    expect(await screen.findByRole('img', { name: 'A river at dusk' })).toBeInTheDocument();
    expect(paths).toEqual([`/stories/s1/assets/${assetId}`]);
  });

  it('observes a placeholder that appears after the first render', async () => {
    const paths: string[] = [];
    vi.mocked(apiFetchBlob).mockImplementation(async (path: string) => {
      paths.push(path);
      return new Blob(['x'], { type: 'image/webp' });
    });
    const cover = (path: string | null) => (
      <AssetImage
        path={path}
        alt="Cover"
        lazy
        className="cover"
        placeholderClassName="placeholder"
        loadingLabel="Loading cover"
        fallback={<p>No cover</p>}
      />
    );
    // A card whose cover arrives on a later read of the list.
    const { rerender } = render(cover(null));
    expect(screen.getByText('No cover')).toBeInTheDocument();
    rerender(cover('/stories/s1/assets/cover'));
    expect(await screen.findByRole('img', { name: 'Loading cover' })).toBeInTheDocument();

    const placeholder = screen.getByRole('img', { name: 'Loading cover' });
    await waitFor(() => expect(observers.some((o) => o.targets.includes(placeholder))).toBe(true));
    const { callback } = observers.find((o) => o.targets.includes(placeholder))!;
    act(() =>
      callback([{ isIntersecting: true, target: placeholder } as unknown as IntersectionObserverEntry], {} as IntersectionObserver),
    );
    expect(await screen.findByRole('img', { name: 'Cover' })).toBeInTheDocument();
    expect(paths).toEqual(['/stories/s1/assets/cover']);
  });
});
