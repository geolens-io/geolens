import { render, screen } from '@testing-library/react';
import { logger } from '@/lib/logger';
import { WidgetView } from '../WidgetView';
import { defineWidget } from '../contract';
import MarkdownTextRenderer from '../markdown/MarkdownTextRenderer';
import { MARKDOWN_TEXT_MAX_LENGTH, markdownTextWidget } from '../markdown/definition';
import { parseStoredWidget } from '../registry';

function renderMarkdown(text: string) {
  return render(<MarkdownTextRenderer config={{ text }} />);
}

describe('Markdown text widget', () => {
  it('renders Markdown formatting', () => {
    renderMarkdown('## Heading\n\n- one\n- **two**');
    expect(screen.getByRole('heading', { level: 4, name: 'Heading' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('nests headings under the chapter heading, h1 as h3 down to h6', () => {
    renderMarkdown('# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six');
    expect(screen.getAllByRole('heading').map((h) => h.tagName)).toEqual(['H3', 'H4', 'H5', 'H6', 'H6', 'H6']);
  });

  it('never renders raw HTML', () => {
    const { container } = renderMarkdown(
      '<script>window.pwned = 1</script>\n\nHi <b onclick="x()">bold</b> <iframe src="https://example.com"></iframe>',
    );
    expect(container.querySelector('script, b, iframe, [onclick]')).toBeNull();
    expect(container.textContent).toContain('<b onclick="x()">');
  });

  it('marks links noopener noreferrer nofollow', () => {
    renderMarkdown('[GeoLens](https://example.com/page)');
    const link = screen.getByRole('link', { name: 'GeoLens' });
    expect(link).toHaveAttribute('href', 'https://example.com/page');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow');
  });

  it('drops javascript: link targets', () => {
    renderMarkdown('[click](javascript:alert(1))');
    expect(screen.getByText('click').getAttribute('href') ?? '').not.toMatch(/javascript/i);
  });

  it('shows a notice instead of loading an image', () => {
    const { container } = renderMarkdown(
      '![River at dusk](https://tracker.example.com/pixel.png)\n\n![](/api/v1/anything.png)',
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Image not shown: River at dusk')).toBeInTheDocument();
    expect(screen.getByText('Image not shown')).toBeInTheDocument();
  });

  it('never loads an event-handler image, and shows other unsafe link targets as plain anchors without a destination', () => {
    const { container } = renderMarkdown(
      '<img src=x onerror="window.pwned = 1">\n\n[a](javascript:alert(1)) [b](data:text/html,x) [c](tel:555) [d](irc://h/c) [e](https://example.com) [f](mailto:a@b.co) [g](/relative)',
    );
    expect(container.querySelector('img, [onerror]')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=');
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['', '', '', '', 'https://example.com', 'mailto:a@b.co', '/relative']);
  });

  it('draws story headings at the default level with the styling they always had', () => {
    const { container } = renderMarkdown('# One\n\n## Two');
    expect([...container.querySelectorAll('h3,h4')].map((h) => h.outerHTML)).toEqual([
      '<h3>One</h3>',
      '<h4>Two</h4>',
    ]);
    expect(container.firstElementChild?.className).toBe(
      'space-y-3 break-words text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:font-mono [&_h3]:text-lg [&_h3]:font-semibold [&_h4]:font-semibold [&_h5]:font-semibold [&_h6]:font-semibold [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5',
    );
  });

  it('starts its headings at the level it is given, to h6', () => {
    const { container } = render(
      <MarkdownTextRenderer config={{ text: '# One\n\n## Two\n\n### Three' }} headingLevel={4} />,
    );
    expect([...container.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => h.tagName)).toEqual(['H4', 'H5', 'H6']);
  });

  it('accepts only a text string within the length cap', () => {
    const parse = (config: unknown) => markdownTextWidget.parseConfig(config, 1);
    expect(parse({ text: 'x'.repeat(MARKDOWN_TEXT_MAX_LENGTH) })).not.toBeNull();
    expect(parse({ text: 'x'.repeat(MARKDOWN_TEXT_MAX_LENGTH + 1) })).toBeNull();
    // The server counts code points, so an emoji is one character, not two.
    expect(parse({ text: '🗺'.repeat(MARKDOWN_TEXT_MAX_LENGTH) })).not.toBeNull();
    expect(parse({})).toBeNull();
    expect(parse({ text: 1 })).toBeNull();
    expect(parse({ text: 'x', html: '<b>' })).toBeNull();
    expect(parse({ markdown: 'x' })).toBeNull();
  });
});

describe('Markdown text widget on a dashboard', () => {
  const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
  const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
  const text = { id, type: 'markdown', v: 1, config: { text: 'Hi' } };

  it('takes no layer, scope or data request', () => {
    expect(parseStoredWidget(text, 'dashboard')).toMatchObject({ ok: true, instance: text });
    expect(markdownTextWidget.dataRequest).toBeUndefined();
    for (const extra of [{ layer_id: layerId }, { scope: 'layer' }]) {
      expect(parseStoredWidget({ ...text, ...extra }, 'dashboard')).toEqual({ ok: false, reason: 'malformed' });
    }
  });

  it('still needs a layer on a type that summarizes one', () => {
    const indicator = { id, type: 'indicator', v: 1, config: { stat: 'count', column: null } };
    expect(parseStoredWidget(indicator, 'dashboard')).toEqual({ ok: false, reason: 'malformed' });
  });
});

describe('WidgetView with the Markdown text widget', () => {
  const config = { text: 'Some **bold** text.' };
  const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';

  afterEach(() => vi.restoreAllMocks());

  it('swaps the text fallback for the lazy renderer', async () => {
    const parsed = parseStoredWidget({ id, type: 'markdown', v: 1, config }, 'story');
    const { container } = render(<WidgetView parsed={parsed} />);
    await vi.waitFor(() => expect(container.querySelector('strong')).toHaveTextContent('bold'));
  });

  it('keeps the text fallback when the renderer fails to load', async () => {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const definition = defineWidget<unknown>({
      ...markdownTextWidget,
      loadRenderer: () => Promise.reject(new Error('chunk failed')),
    });
    render(
      <WidgetView parsed={{ ok: true, definition, instance: { id, type: 'markdown', v: 1, config } }} />,
    );
    await vi.waitFor(() => expect(logged).toHaveBeenCalled());
    expect(screen.getByText('Some **bold** text.')).toBeInTheDocument();
  });
});
