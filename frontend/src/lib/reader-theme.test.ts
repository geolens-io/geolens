import { readerLogoUrl, readerThemeStyle } from './reader-theme';

// Relative luminance of the light and dark --background tokens.
const BACKGROUND = { light: 0.9557, dark: 0.0031 };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(hex: string, background: number): number {
  const l = luminance(hex);
  return (Math.max(l, background) + 0.05) / (Math.min(l, background) + 0.05);
}

function primary(accent: string, mode: 'light' | 'dark'): string {
  return (readerThemeStyle({ accent }, mode) as Record<string, string>)['--primary'];
}

describe('readerThemeStyle', () => {
  it('leaves the standard tokens without a theme', () => {
    expect(readerThemeStyle(null, 'light')).toBeUndefined();
    expect(readerThemeStyle(undefined, 'dark')).toBeUndefined();
    expect(readerThemeStyle({ accent: null, logo_url: null, font_family: null }, 'light')).toBeUndefined();
  });

  it('uses an accent that is already readable unchanged, with light text on it', () => {
    expect(readerThemeStyle({ accent: '#0a3d62' }, 'light')).toEqual({
      '--primary': '#0a3d62',
      '--primary-foreground': 'oklch(0.985 0 0)',
    });
  });

  it.each(['#ffd23f', '#ffffff', '#7fdbff'])('darkens %s until links read on the light background', (accent) => {
    const adjusted = primary(accent, 'light');
    expect(adjusted).not.toBe(accent);
    expect(contrast(adjusted, BACKGROUND.light)).toBeGreaterThanOrEqual(4.5);
    expect(luminance(adjusted)).toBeLessThan(luminance(accent));
  });

  it('lightens a dark accent on the dark background instead of darkening it', () => {
    const adjusted = primary('#0a3d62', 'dark');
    expect(contrast(adjusted, BACKGROUND.dark)).toBeGreaterThanOrEqual(4.5);
    expect(luminance(adjusted)).toBeGreaterThan(luminance('#0a3d62'));
    expect(primary('#ffd23f', 'dark')).toBe('#ffd23f');
  });

  it('keeps the hue when it adjusts the accent', () => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(primary('#ffd23f', 'light').slice(i, i + 2), 16));
    expect(r).toBeGreaterThan(g);
    expect(g).toBeGreaterThan(b);
  });

  it('picks the text colour on the adjusted accent', () => {
    expect(readerThemeStyle({ accent: '#ffd23f' }, 'dark')).toMatchObject({
      '--primary-foreground': 'oklch(0.145 0.005 250)',
    });
  });

  it('puts the font first and keeps the standard font after it', () => {
    expect(readerThemeStyle({ font_family: "'Source Sans 3'" }, 'light')).toEqual({
      fontFamily: "'Source Sans 3', var(--default-font-family)",
    });
  });

  it('ignores values outside the allowed set', () => {
    expect(
      readerThemeStyle({ accent: 'red; color: blue', font_family: 'x; background: url(y)' }, 'light'),
    ).toBeUndefined();
  });
});

describe('readerLogoUrl', () => {
  it('returns only an https logo', () => {
    expect(readerLogoUrl({ logo_url: 'https://cdn.example.com/logo.svg' })).toBe('https://cdn.example.com/logo.svg');
    expect(readerLogoUrl({ logo_url: 'javascript:alert(1)' })).toBeUndefined();
    expect(readerLogoUrl({ logo_url: 'http://cdn.example.com/logo.svg' })).toBeUndefined();
    expect(readerLogoUrl(null)).toBeUndefined();
  });
});
