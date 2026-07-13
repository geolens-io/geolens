import { describe, expect, it } from 'vitest';
import { MAP_COLORS } from '@/lib/map-colors';

const rawCssModules = import.meta.glob('/src/index.css', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const INDEX_CSS = rawCssModules['/src/index.css'];

interface OklchColor {
  lightness: number;
  chroma: number;
  hue: number;
}

function lightThemeBlock(css: string): string {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const match = withoutComments.match(/:root\s*\{([^}]+)\}/);
  if (!match) throw new Error('Could not find the :root light-theme token block in index.css');
  return match[1];
}

function readOklchToken(block: string, token: string): OklchColor {
  const number = '(-?(?:\\d+(?:\\.\\d+)?|\\.\\d+))';
  const match = block.match(
    new RegExp(`^\\s*${token.replaceAll('-', '\\-')}\\s*:\\s*oklch\\(\\s*${number}\\s+${number}\\s+${number}\\s*\\)\\s*;`, 'm'),
  );
  if (!match) throw new Error(`Expected ${token} to be a three-channel oklch() token in :root`);
  return {
    lightness: Number(match[1]),
    chroma: Number(match[2]),
    hue: Number(match[3]),
  };
}

/** CSS Color 4 OKLCH -> OKLab -> linear sRGB, clipped to a six-digit hex color. */
function oklchToSrgbHex({ lightness, chroma, hue }: OklchColor): string {
  const hueRadians = (hue * Math.PI) / 180;
  const a = chroma * Math.cos(hueRadians);
  const b = chroma * Math.sin(hueRadians);

  const lPrime = lightness + 0.3963377774 * a + 0.2158037573 * b;
  const mPrime = lightness - 0.1055613458 * a - 0.0638541728 * b;
  const sPrime = lightness - 0.0894841775 * a - 1.291485548 * b;
  const l = lPrime ** 3;
  const m = mPrime ** 3;
  const s = sPrime ** 3;

  const linearRgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];

  const channels = linearRgb.map((channel) => {
    const encoded = channel >= 0.0031308
      ? 1.055 * channel ** (1 / 2.4) - 0.055
      : 12.92 * channel;
    return Math.round(Math.min(1, Math.max(0, encoded)) * 255);
  });

  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

describe('MAP_COLORS design-token parity', () => {
  const root = lightThemeBlock(INDEX_CSS);
  const brandedPrimary = '#3b6fd4';

  it('uses the CSS Color 4 conversion matrix', () => {
    expect(oklchToSrgbHex({
      lightness: 0.6279553606,
      chroma: 0.2576833077,
      hue: 29.2338851923,
    })).toBe('#ff0000');
  });

  it('uses branding v0.2.0\'s frozen sRGB primary for MapLibre paints', () => {
    expect(readOklchToken(root, '--primary')).toEqual(readOklchToken(root, '--viz-1'));
    expect(MAP_COLORS.default.fill).toBe(brandedPrimary);
    expect(MAP_COLORS.categorical[0]).toBe(brandedPrimary);
  });

  it('keeps the default stroke synchronized with the light primary-700 token', () => {
    expect(MAP_COLORS.default.stroke).toBe(oklchToSrgbHex(readOklchToken(root, '--primary-700')));
  });

  it('keeps non-frozen categorical colors synchronized with light --viz-2..8', () => {
    const tokenColors = Array.from({ length: 7 }, (_, index) =>
      oklchToSrgbHex(readOklchToken(root, `--viz-${index + 2}`)),
    );

    expect(MAP_COLORS.categorical.slice(1)).toEqual(tokenColors);
  });
});
