/** fix(#1502): a blank auto-captured thumbnail must be skipped, not uploaded.
 *
 *  The capture pipeline is fail-open at every stage (source-wait deadline,
 *  idle timeout), so a slow first render can hand doCapture an unpainted
 *  canvas. The gate that schedules auto-capture is `hasThumbnail`, so one
 *  blank upload used to disqualify the map from every future attempt — the
 *  demo served two solid-colour thumbnails (stddev 0.00 and 1.88) for months.
 *  These tests pin the discriminator that now stands in front of the upload:
 *  per-channel variance, a deviant-pixel rescue for sparse maps, and fail-open
 *  behaviour whenever pixels are unreadable.
 *
 *  jsdom has no 2D canvas, so the pixel math is exercised on synthetic data
 *  and `isEffectivelyBlank` through a stub canvas — including the fail-open
 *  path, which must never block an upload just because pixels were unreadable.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  maxChannelStddev,
  isBlankPixelData,
  isEffectivelyBlank,
  shouldAutoCapture,
  rearmAutoCapture,
  __resetThumbnailDebounceForTests,
  BLANK_CHANNEL_STDDEV,
  SPARSE_PIXEL_COUNT,
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

describe('maxChannelStddev', () => {
  it('is ~0 for a solid fill — the demo Manhattan failure shape', () => {
    // Not exactly 0: sumSq/n - mean^2 carries float rounding at the 1e-7
    // scale, which the sqrt turns into ~1e-4 at worst. What matters is that
    // it sits far below the threshold, not that it is a perfect zero.
    expect(maxChannelStddev(rgba(1000, () => [241, 241, 241]))).toBeLessThan(0.001);
  });

  it('is small for near-uniform noise — the demo heatmap failure shape (1.88)', () => {
    // +/-2 around a base grey: variance stays low single digits.
    const data = rgba(1000, (i) => {
      const v = 198 + (i % 5) - 2;
      return [v, v, v];
    });
    const sd = maxChannelStddev(data);
    expect(sd).toBeGreaterThan(0);
    expect(sd).toBeLessThan(BLANK_CHANNEL_STDDEV);
  });

  it('is large for real content — alternating dark/light like map linework', () => {
    const data = rgba(1000, (i) => (i % 2 === 0 ? [30, 30, 30] : [220, 220, 220]));
    expect(maxChannelStddev(data)).toBeGreaterThan(BLANK_CHANNEL_STDDEV * 10);
  });

  /** fix(#1504 review round 3): red (255,0,0) and green (0,130,0) sit at the
   *  SAME luminance (~76.3), so a luminance statistic reads a red/green
   *  categorical map as a solid fill. Per-channel stddev sees it plainly. */
  it('sees isoluminant hue variation a luminance statistic cannot', () => {
    const data = rgba(1000, (i) => (i % 2 === 0 ? [255, 0, 0] : [0, 130, 0]));
    const lumA = 0.299 * 255;
    const lumB = 0.587 * 130;
    expect(Math.abs(lumA - lumB)).toBeLessThan(0.5); // genuinely isoluminant
    expect(maxChannelStddev(data)).toBeGreaterThan(BLANK_CHANNEL_STDDEV * 10);
  });

  it('returns 0 on empty data rather than NaN', () => {
    expect(maxChannelStddev(new Uint8ClampedArray(0))).toBe(0);
  });
});

describe('isBlankPixelData', () => {
  it('flags both demo failure shapes: exact uniform and near-uniform noise', () => {
    expect(isBlankPixelData(rgba(100_000, () => [241, 241, 241]))).toBe(true);
    const noisy = rgba(100_000, (i) => {
      const v = 198 + (i % 5) - 2;
      return [v, v, v];
    });
    expect(isBlankPixelData(noisy)).toBe(true);
  });

  /** fix(#1504 review round 2): a lone point feature on the "No basemap"
   *  uniform background sits UNDER the stddev threshold — the deviant-pixel
   *  rescue is the only thing that saves it. The first assertion pins the
   *  counterfactual: the stddev screen alone rejects this frame. */
  it('rescues a sparse map — a 20px dot the stddev screen alone would reject', () => {
    const dot = rgba(100_000, (i) => (i < 20 ? [10, 10, 10] : [200, 200, 200]));
    expect(maxChannelStddev(dot)).toBeLessThan(BLANK_CHANNEL_STDDEV); // would reject
    expect(isBlankPixelData(dot)).toBe(false); // rescued
  });

  /** fix(#1504 review round 3): the sparse rescue must also be channel-space.
   *  A red dot on an isoluminant green ground deviates by ~0 in luminance but
   *  by 255 in the red channel. */
  it('rescues an isoluminant sparse dot — invisible to luminance entirely', () => {
    const dot = rgba(100_000, (i) => (i < 20 ? [255, 0, 0] : [0, 130, 0]));
    expect(maxChannelStddev(dot)).toBeLessThan(BLANK_CHANNEL_STDDEV); // sparse: fails the screen
    expect(isBlankPixelData(dot)).toBe(false); // rescued per-channel
  });

  it('does not let stray outlier pixels below the count floor rescue a blank', () => {
    const stray = rgba(100_000, (i) => (i < SPARSE_PIXEL_COUNT - 3 ? [10, 10, 10] : [200, 200, 200]));
    expect(isBlankPixelData(stray)).toBe(true);
  });

  it('passes real content on variance alone', () => {
    const data = rgba(1000, (i) => (i % 2 === 0 ? [30, 30, 30] : [220, 220, 220]));
    expect(isBlankPixelData(data)).toBe(false);
  });

  it('passes an isoluminant categorical split on channel variance alone', () => {
    const data = rgba(1000, (i) => (i % 2 === 0 ? [255, 0, 0] : [0, 130, 0]));
    expect(isBlankPixelData(data)).toBe(false);
  });

  it('fails open on empty data — unreadable pixels must never block an upload', () => {
    expect(isBlankPixelData(new Uint8ClampedArray(0))).toBe(false);
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
