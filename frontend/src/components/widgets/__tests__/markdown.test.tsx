import { render, screen } from '@testing-library/react';
import { logger } from '@/lib/logger';
import { WidgetView } from '../WidgetView';
import { defineWidget } from '../contract';
import MarkdownTextRenderer from '../markdown/MarkdownTextRenderer';
import { MARKDOWN_TEXT_MAX_LENGTH, markdownTextWidget } from '../markdown/definition';
import { parseStoredWidget } from '../registry';

function renderMarkdown(markdown: string) {
  return render(<MarkdownTextRenderer config={{ markdown }} />);
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

  it('accepts only a markdown string within the length cap', () => {
    const parse = (config: unknown) => markdownTextWidget.parseConfig(config, 1);
    expect(parse({ markdown: 'x'.repeat(MARKDOWN_TEXT_MAX_LENGTH) })).not.toBeNull();
    expect(parse({ markdown: 'x'.repeat(MARKDOWN_TEXT_MAX_LENGTH + 1) })).toBeNull();
    expect(parse({})).toBeNull();
    expect(parse({ markdown: 1 })).toBeNull();
    expect(parse({ markdown: 'x', html: '<b>' })).toBeNull();
  });
});

describe('WidgetView with the Markdown text widget', () => {
  const config = { markdown: 'Some **bold** text.' };

  afterEach(() => vi.restoreAllMocks());

  it('swaps the text fallback for the lazy renderer', async () => {
    const parsed = parseStoredWidget({ type: 'markdown', v: 1, config }, 'story');
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
      <WidgetView parsed={{ ok: true, definition, instance: { type: 'markdown', v: 1, config } }} />,
    );
    await vi.waitFor(() => expect(logged).toHaveBeenCalled());
    expect(screen.getByText('Some **bold** text.')).toBeInTheDocument();
  });
});
