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
    expect(screen.getByRole('heading', { level: 2, name: 'Heading' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
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
