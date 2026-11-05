import { render, screen } from '@/test/test-utils';
import type { StoryFrameHost } from '@/types/api';
import { frameUrlHost, normalizeFrameHost } from '../embed/frame';
import { parseStoredWidget } from '../registry';
import { WidgetView } from '../WidgetView';

let approved: StoryFrameHost[] = [];

vi.mock('@/api/stories', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/stories')>()),
  getStoryFrameHosts: vi.fn(async () => approved),
}));

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const URL_ON_MEDIA = 'https://media.example.org/v/1?t=30';

function block(type: 'embed' | 'video', config: Record<string, unknown> = { url: URL_ON_MEDIA, title: 'Field visit' }) {
  return { id, type, v: 1, config };
}

function renderBlock(raw: unknown) {
  return render(<WidgetView parsed={parseStoredWidget(raw, 'story')} />);
}

describe('frame addresses', () => {
  it('take only https on a plain host name, with an optional 443', () => {
    expect(frameUrlHost(URL_ON_MEDIA)).toBe('media.example.org');
    expect(frameUrlHost('HTTPS://Media.Example.org:443/a')).toBe('media.example.org');
    for (const url of [
      'http://media.example.org/a',
      'https://user@media.example.org/a',
      'https://media.example.org:8443/a',
      'https://10.0.0.1/a',
      'https://[::1]/a',
      'https://localhost/a',
      'https://media.example.org\\@evil.example.com/',
      'https://media.example.org/a b',
      'javascript:alert(1)',
      '//media.example.org/a',
    ]) {
      expect(frameUrlHost(url), url).toBeNull();
    }
  });

  it('name hosts the way the admin setting stores them', () => {
    expect(normalizeFrameHost(' Media.Example.ORG ')).toBe('media.example.org');
    for (const host of ['*.example.org', 'https://media.example.org', 'media.example.org:8443', 'localhost', '10.0.0.1']) {
      expect(normalizeFrameHost(host), host).toBeNull();
    }
  });
});

describe.each(['embed', 'video'] as const)('%s block instances', (type) => {
  it('hold a URL and a required title, never HTML', () => {
    expect(parseStoredWidget(block(type), 'story').ok).toBe(true);
    for (const config of [
      { url: URL_ON_MEDIA, title: ' ' },
      { url: URL_ON_MEDIA },
      { url: 'http://media.example.org/v/1', title: 'A' },
      { url: URL_ON_MEDIA, title: 'A', html: '<iframe src="x"></iframe>' },
      { url: URL_ON_MEDIA, title: 'x'.repeat(201) },
    ]) {
      expect(parseStoredWidget(block(type, config), 'story').ok, JSON.stringify(config)).toBe(false);
    }
  });

  it('are not dashboard widgets', () => {
    expect(parseStoredWidget(block(type), 'dashboard')).toMatchObject({ ok: false });
  });
});

describe('frame block renderer', () => {
  it('frames an approved host in a lazy, titled sandbox without its own origin', async () => {
    approved = [{ host: 'media.example.org', allow_same_origin: false }];
    renderBlock(block('embed'));
    const frame = await screen.findByTitle('Field visit');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('src', URL_ON_MEDIA);
    expect(frame).toHaveAttribute('loading', 'lazy');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-popups');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('keeps the host origin only for a host the admin opted in', async () => {
    approved = [{ host: 'media.example.org', allow_same_origin: true }];
    renderBlock(block('video'));
    const frame = await screen.findByTitle('Field visit');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-popups allow-same-origin');
    expect(frame).toHaveClass('aspect-video');
    expect(frame).toHaveAttribute('allowfullscreen');
  });

  it.each([
    ['a host that is no longer listed', [{ host: 'other.example.org', allow_same_origin: true }]],
    ['an empty list', []],
  ])('shows a placeholder with a link to the original for %s', async (_, hosts) => {
    approved = hosts;
    const { container } = renderBlock(block('video'));
    expect(await screen.findByText(/This video can't be shown here/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Field visit/ });
    expect(link).toHaveAttribute('href', URL_ON_MEDIA);
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(container.querySelector('iframe')).toBeNull();
  });
});
