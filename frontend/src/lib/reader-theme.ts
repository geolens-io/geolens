import type { CSSProperties } from 'react';
import type { components } from '@/types/api.generated';

export type ReaderTheme = components['schemas']['ReaderTheme'];

const HEX = /^#[0-9a-f]{6}$/i;
const FONT = /^[A-Za-z0-9 ,'"-]{1,100}$/;
// The light and dark text tokens from index.css.
const LIGHT_TEXT = 'oklch(0.985 0 0)';
const DARK_TEXT = 'oklch(0.145 0.005 250)';

function relativeLuminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Text on the accent: light or dark, whichever contrasts more. */
function foregroundOn(hex: string): string {
  const l = relativeLuminance(hex);
  return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? LIGHT_TEXT : DARK_TEXT;
}

/**
 * The style for a reader page's root element: the theme's accent as the
 * primary tokens and its font first in the font list, scoped to that element.
 * Undefined without a theme, so the page keeps the standard tokens.
 */
export function readerThemeStyle(theme: ReaderTheme | null | undefined): CSSProperties | undefined {
  if (!theme) return undefined;
  const style: Record<string, string> = {};
  if (theme.accent && HEX.test(theme.accent)) {
    style['--primary'] = theme.accent;
    style['--primary-foreground'] = foregroundOn(theme.accent);
  }
  if (theme.font_family && FONT.test(theme.font_family)) {
    style.fontFamily = `${theme.font_family}, var(--default-font-family)`;
  }
  return Object.keys(style).length > 0 ? (style as CSSProperties) : undefined;
}

/** The theme's logo URL when it is https, else undefined. */
export function readerLogoUrl(theme: ReaderTheme | null | undefined): string | undefined {
  return theme?.logo_url?.startsWith('https://') ? theme.logo_url : undefined;
}
