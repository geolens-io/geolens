import { render, screen } from '@/test/test-utils';
import { isSafeHttpUrl } from '@/lib/safe-http-url';
import { buttonWidget } from '../button/definition';
import { separatorWidget } from '../separator/definition';
import { parseStoredWidget, checkWidgetWrite } from '../registry';
import { WidgetView } from '../WidgetView';

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const button = (config: unknown) => ({ id, type: 'button', v: 1, config });
const separator = (config: unknown) => ({ id, type: 'separator', v: 1, config });

function renderBlock(raw: unknown) {
  return render(<WidgetView parsed={parseStoredWidget(raw, 'story')} />);
}

describe('button block instances', () => {
  it('read and write back the label, address and new-tab setting', () => {
    const raw = button({ label: 'Read the report', url: 'https://example.com/r', new_tab: true });
    expect(parseStoredWidget(raw, 'story')).toMatchObject({ ok: true, instance: raw });
    expect(checkWidgetWrite(raw, 'story')).toEqual({ ok: true });
    expect(buttonWidget.parseConfig({ label: 'Go', url: 'https://example.com', new_tab: false }, 1)).toEqual({
      label: 'Go',
      url: 'https://example.com',
    });
  });

  it('need a label and an address of the right type, as the server does', () => {
    for (const config of [
      { url: 'https://example.com' },
      { label: 'Go' },
      { label: '  ', url: 'https://example.com' },
      { label: 'x'.repeat(121), url: 'https://example.com' },
      { label: 'Go', url: 'https://example.com/' + 'a'.repeat(2048) },
      { label: 'Go', url: 'https://example.com', new_tab: 'yes' },
      { label: 'Go', url: 'https://example.com', colour: 'red' },
    ]) {
      expect(parseStoredWidget(button(config), 'story').ok, JSON.stringify(config)).toBe(false);
    }
  });

  it('accepts only http and https addresses with a host', () => {
    for (const url of ['http://example.com', 'HTTPS://Example.com/a?b=1#c']) expect(isSafeHttpUrl(url), url).toBe(true);
    for (const url of [
      'javascript:alert(1)',
      'JavaScript:alert(1)',
      'javascript://example.com/%0Aalert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
      '//example.com',
      '/path',
      'example.com',
      'https://',
      ' https://example.com',
      'https://exa mple.com',
      'java\nscript:alert(1)',
      '',
    ]) {
      expect(isSafeHttpUrl(url), JSON.stringify(url)).toBe(false);
    }
  });
});

describe('button block renderer', () => {
  it('links to the address in the same tab, with no target', async () => {
    renderBlock(button({ label: 'Read the report', url: 'https://example.com/r' }));
    const link = await screen.findByRole('link', { name: 'Read the report' });
    expect(link).toHaveAttribute('href', 'https://example.com/r');
    expect(link).not.toHaveAttribute('target');
  });

  it('opens a new tab with rel noopener noreferrer and says so', async () => {
    renderBlock(button({ label: 'Read the report', url: 'https://example.com/r', new_tab: true }));
    const link = await screen.findByRole('link', { name: 'Read the report (opens in a new tab)' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it.each(['javascript:alert(1)', 'data:text/html,hi', 'ftp://example.com/a'])(
    'shows the label as plain text for a stored %s address',
    async (url) => {
      renderBlock(button({ label: 'Read the report', url, new_tab: true }));
      expect(await screen.findByText('Read the report')).toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(document.querySelector('a')).toBeNull();
    },
  );
});

describe('separator block', () => {
  it('reads a line or a gap, and a line when the style is left out', () => {
    expect(separatorWidget.parseConfig({}, 1)).toEqual({ style: 'line' });
    expect(separatorWidget.parseConfig({ style: 'gap' }, 1)).toEqual({ style: 'gap' });
    for (const config of [{ style: 'dots' }, { text: 'x' }, { style: 'line', text: 'x' }]) {
      expect(parseStoredWidget(separator(config), 'story').ok, JSON.stringify(config)).toBe(false);
    }
  });

  it.each(['line', 'gap'])('is a separator to assistive technology as a %s', async (style) => {
    renderBlock(separator({ style }));
    const rule = await screen.findByRole('separator');
    expect(rule).not.toHaveAttribute('aria-hidden');
    expect(rule.textContent).toBe('');
  });

  it('is not a dashboard widget', () => {
    expect(parseStoredWidget(separator({ style: 'line' }), 'dashboard')).toMatchObject({ ok: false });
  });
});
