/** fix(#1502): a blank auto-captured thumbnail must be skipped, not uploaded.
 *
 *  The capture pipeline is fail-open at every stage (source-wait deadline,
 *  idle timeout), so a slow first render can hand doCapture an unpainted
 *  canvas. The gate that schedules auto-capture is `hasThumbnail`, so one
 *  blank upload used to disqualify the map from every future attempt — the
 *  demo served two solid-colour thumbnails (luminance stddev 0.00 and 1.88)
 *  for months. These tests pin the discriminator that now stands in front of
 *  the upload.
 *
 *  jsdom has no 2D canvas, so `luminanceStddev` is exercised on synthetic
 *  pixel data and `isEffectivelyBlank` through a stub canvas — including the
 *  fail-open path, which must never block an upload just because pixels were
 *  unreadable.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  luminanceStddev,
  isEffectivelyBlank,
  shouldAutoCapture,
  rearmAutoCapture,
  __resetThumbnailDebounceForTests,
  BLANK_LUMINANCE_STDDEV,
} from '../use-builder-save';

beforeEach(() => {
  __resetThumbnailDebounceForTests();
});

/** RGBA buffer of `n` pixels produced by `fn(index) -> [r,g,b]`. */
function rgba(n: number, fn: (i: number) => [number, number, number]): Uint8ClampedArray {
  const out = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) {
    const [r, g, b] = fn(i);
    out[i * 4] = r;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = b;
    out[i * 4 + 3] = 255;
  }
  return out;
}

function stubCanvas(data: Uint8ClampedArray | null): HTMLCanvasElement {
  return {
    width: 400,
    height: 250,
    getContext: () =>
      data === null
        ? null
        : ({ getImageData: () => ({ data }) } as unknown as CanvasRenderingContext2D),
  } as unknown as HTMLCanvasElement;
}

describe('luminanceStddev', () => {
  it('is ~0 for a solid fill — the demo Manhattan failure shape', () => {
    // Not exactly 0: sumSq/n - mean^2 carries float rounding at the 1e-7
    // scale, which the sqrt turns into ~1e-4 at worst. What matters is that
    // it sits far below the threshold, not that it is a perfect zero.
    expect(luminanceStddev(rgba(1000, () => [241, 241, 241]))).toBeLessThan(0.001);
  });

  it('is small for near-uniform noise — the demo heatmap failure shape (1.88)', () => {
    // +/-2 around a base grey: variance stays low single digits.
    const data = rgba(1000, (i) => {
      const v = 198 + (i % 5) - 2;
      return [v, v, v];
    });
    const sd = luminanceStddev(data, 1);
    expect(sd).toBeGreaterThan(0);
    expect(sd).toBeLessThan(BLANK_LUMINANCE_STDDEV);
  });

  it('is large for real content — alternating dark/light like map linework', () => {
    const data = rgba(1000, (i) => (i % 2 === 0 ? [30, 30, 30] : [220, 220, 220]));
    expect(luminanceStddev(data, 1)).toBeGreaterThan(BLANK_LUMINANCE_STDDEV * 10);
  });

  it('weights channels as luminance, not average — pure-chroma variation still counts', () => {
    // Red/blue alternation: identical channel averages, different luminance.
    const data = rgba(1000, (i) => (i % 2 === 0 ? [255, 0, 0] : [0, 0, 255]));
    expect(luminanceStddev(data, 1)).toBeGreaterThan(BLANK_LUMINANCE_STDDEV);
  });

  it('returns 0 on empty data rather than NaN', () => {
    expect(luminanceStddev(new Uint8ClampedArray(0))).toBe(0);
  });
});

describe('isEffectivelyBlank', () => {
  it('flags a solid-colour canvas', () => {
    expect(isEffectivelyBlank(stubCanvas(rgba(1000, () => [200, 200, 200])))).toBe(true);
  });

  it('passes a canvas with real variation', () => {
    const data = rgba(1000, (i) => (i % 3 === 0 ? [20, 40, 60] : [180, 200, 230]));
    expect(isEffectivelyBlank(stubCanvas(data))).toBe(false);
  });

  it('fails open when no 2D context is available (jsdom, worker contexts)', () => {
    // "Cannot judge" must mean "upload as before", never "block the upload".
    expect(isEffectivelyBlank(stubCanvas(null))).toBe(false);
  });

  it('fails open when getImageData throws (tainted canvas)', () => {
    const canvas = {
      width: 400,
      height: 250,
      getContext: () =>
        ({
          getImageData: () => {
            throw new DOMException('tainted');
          },
        }) as unknown as CanvasRenderingContext2D,
    } as unknown as HTMLCanvasElement;
    expect(isEffectivelyBlank(canvas)).toBe(false);
  });
});

describe('rearmAutoCapture', () => {
  /** fix(#1504 review): the SF-07 LRU marks a map "attempted" at schedule
   *  time and survives unmount/remount, so a rejected blank frame must clear
   *  it — otherwise "retry on next open" only holds across hard reloads. */
  it('re-arms a map after a rejected frame so the next open retries', () => {
    expect(shouldAutoCapture('m1', 'u1')).toBe(true);
    expect(shouldAutoCapture('m1', 'u1')).toBe(false); // armed for the session
    rearmAutoCapture('m1');
    expect(shouldAutoCapture('m1', 'u1')).toBe(true); // retry allowed again
  });

  it('clears every user bucket for the map, and only that map', () => {
    shouldAutoCapture('m1', 'u1');
    shouldAutoCapture('m1', null); // anon bucket for the same map
    shouldAutoCapture('m2', 'u1');
    rearmAutoCapture('m1');
    expect(shouldAutoCapture('m1', 'u1')).toBe(true);
    expect(shouldAutoCapture('m1', null)).toBe(true);
    expect(shouldAutoCapture('m2', 'u1')).toBe(false); // untouched
  });
});
