import type { CSSProperties } from 'react';
import type { components } from '@/types/api.generated';

export type ReaderTheme = components['schemas']['ReaderTheme'];
type ColorMode = 'light' | 'dark';

const HEX = /^#[0-9a-f]{6}$/i;
const FONT = /^[A-Za-z0-9 ,'"-]{1,100}$/;
// The light and dark text tokens from index.css.
const LIGHT_TEXT = 'oklch(0.985 0 0)';
const DARK_TEXT = 'oklch(0.145 0.005 250)';
// Relative luminance of the light and dark --background tokens in index.css.
const BACKGROUND_LUMINANCE: Record<ColorMode, number> = { light: 0.9557, dark: 0.0031 };
const MIN_CONTRAST = 4.5;

type Rgb = [number, number, number];

const hexToRgb = (hex: string): Rgb => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as Rgb;
const rgbToHex = (rgb: Rgb) => `#${rgb.map((c) => Math.round(c * 255).toString(16).padStart(2, '0')).join('')}`;

function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a: number, b: number): number {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function rgbToHsl([r, g, b]: Rgb): Rgb {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  return [0, 8, 4].map((n) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))) as Rgb;
}

/**
 * The accent as text on the page background: unchanged when it reaches 4.5:1,
 * else the same hue darkened (light mode) or lightened (dark mode) until it does.
 */
function readableAccent(hex: string, mode: ColorMode): string {
  const background = BACKGROUND_LUMINANCE[mode];
  if (contrastRatio(luminance(hex), background) >= MIN_CONTRAST) return hex;
  const [h, s, l] = rgbToHsl(hexToRgb(hex));
  const step = mode === 'light' ? -0.02 : 0.02;
  for (let i = 1; i <= 50; i++) {
    const candidate = rgbToHex(hslToRgb(h, s, Math.min(1, Math.max(0, l + step * i))));
    if (contrastRatio(luminance(candidate), background) >= MIN_CONTRAST) return candidate;
  }
  return mode === 'light' ? '#000000' : '#ffffff';
}

/** Text on the accent: light or dark, whichever contrasts more. */
function foregroundOn(hex: string): string {
  const l = luminance(hex);
  return contrastRatio(l, 1) >= contrastRatio(l, 0) ? LIGHT_TEXT : DARK_TEXT;
}

/**
 * The style for a reader page's root element: the theme's accent as the
 * primary tokens, readable on the `mode` background, and its font first in
 * the font list, scoped to that element. Undefined without a theme, so the
 * page keeps the standard tokens.
 */
export function readerThemeStyle(theme: ReaderTheme | null | undefined, mode: ColorMode): CSSProperties | undefined {
  if (!theme) return undefined;
  const style: Record<string, string> = {};
  if (theme.accent && HEX.test(theme.accent)) {
    const primary = readableAccent(theme.accent, mode);
    style['--primary'] = primary;
    style['--primary-foreground'] = foregroundOn(primary);
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
