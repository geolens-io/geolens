import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, '../../index.css'), 'utf8');

function oklchToLuminance(l: number, c: number, hDeg: number): number {
  const h = (hDeg * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map((v) => Math.min(1, Math.max(0, v)));
  // Linear sRGB already, so relative luminance needs no gamma step.
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

function luminanceOf(token: string, occurrence: number): number {
  const re = new RegExp(`${token}:\\s*oklch\\(([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)\\)`, 'g');
  const m = [...css.matchAll(re)][occurrence];
  if (!m) throw new Error(`${token} occurrence ${occurrence} not found`);
  return oklchToLuminance(Number(m[1]), Number(m[2]), Number(m[3]));
}

function ratio(a: number, b: number): number {
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

describe('categorical chart palette contrast', () => {
  // Occurrence 0 is the light theme block, 1 the dark theme block.
  for (const [theme, idx] of [['light', 0], ['dark', 1]] as const) {
    for (let n = 1; n <= 8; n++) {
      for (const surface of ['--card', '--background']) {
        it(`--viz-${n} is at least 3:1 on ${surface} (${theme})`, () => {
          expect(
            ratio(luminanceOf(`--viz-${n}`, idx), luminanceOf(`${surface}`, idx)),
          ).toBeGreaterThanOrEqual(3);
        });
      }
    }
  }
});
