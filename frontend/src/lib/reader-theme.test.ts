import { readerLogoUrl, readerThemeStyle } from './reader-theme';

describe('readerThemeStyle', () => {
  it('leaves the standard tokens without a theme', () => {
    expect(readerThemeStyle(null)).toBeUndefined();
    expect(readerThemeStyle(undefined)).toBeUndefined();
    expect(readerThemeStyle({ accent: null, logo_url: null, font_family: null })).toBeUndefined();
  });

  it('sets the primary tokens with readable text on the accent', () => {
    expect(readerThemeStyle({ accent: '#0a3d62' })).toEqual({
      '--primary': '#0a3d62',
      '--primary-foreground': 'oklch(0.985 0 0)',
    });
    expect(readerThemeStyle({ accent: '#ffd23f' })).toMatchObject({
      '--primary-foreground': 'oklch(0.145 0.005 250)',
    });
  });

  it('puts the font first and keeps the standard font after it', () => {
    expect(readerThemeStyle({ font_family: "'Source Sans 3'" })).toEqual({
      fontFamily: "'Source Sans 3', var(--default-font-family)",
    });
  });

  it('ignores values outside the allowed set', () => {
    expect(readerThemeStyle({ accent: 'red; color: blue', font_family: 'x; background: url(y)' })).toBeUndefined();
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
