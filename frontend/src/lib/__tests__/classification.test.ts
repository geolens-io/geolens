import { describe, it, expect } from 'vitest';
import {
  equalIntervalBreaks,
  quantileBreaks,
  jenksBreaks,
  stdDevBreaks,
  manualBreaks,
} from '../classification';

describe('equalIntervalBreaks (existing, regression)', () => {
  it('returns classCount - 1 evenly spaced breaks', () => {
    expect(equalIntervalBreaks(0, 100, 5)).toEqual([20, 40, 60, 80]);
  });
  it('returns [] for classCount < 2', () => {
    expect(equalIntervalBreaks(0, 100, 1)).toEqual([]);
  });
});

describe('quantileBreaks (existing, regression)', () => {
  it('passes through server quantiles unchanged', () => {
    expect(quantileBreaks([10, 25, 60])).toEqual([10, 25, 60]);
  });
});

describe('jenksBreaks', () => {
  it('separates three natural clusters into classCount - 1 ascending breaks', () => {
    // Three obvious clusters: {1,2,3}, {10,11,12}, {20,21,22}.
    // A correct Jenks partition for k=3 puts the breaks between the clusters.
    const breaks = jenksBreaks([1, 2, 3, 10, 11, 12, 20, 21, 22], 3);
    expect(breaks).toHaveLength(2);
    // Ascending invariant.
    expect(breaks[0]).toBeLessThan(breaks[1]);
    // Pinned from the first green run: breaks fall at the start of clusters 2 and 3.
    expect(breaks).toEqual([10, 20]);
  });

  it('produces strictly ascending breaks for a skewed distribution', () => {
    const breaks = jenksBreaks([1, 1, 1, 2, 3, 50, 51, 99, 100], 4);
    expect(breaks).toHaveLength(3);
    for (let i = 1; i < breaks.length; i++) {
      expect(breaks[i]).toBeGreaterThan(breaks[i - 1]);
    }
    // Pinned from the first green run.
    expect(breaks).toEqual([2, 50, 99]);
  });

  it('falls back to equal-interval when there are fewer values than classes', () => {
    // 3 values, 5 classes → fall back to equalIntervalBreaks(min,max,5).
    const breaks = jenksBreaks([0, 50, 100], 5);
    expect(breaks).toEqual(equalIntervalBreaks(0, 100, 5));
  });

  it('returns [] for classCount < 2', () => {
    expect(jenksBreaks([1, 2, 3], 1)).toEqual([]);
  });

  it('clamps an absurd classCount to the number of available values', () => {
    // 4 distinct values, asking for 20 classes — at most 3 breaks possible.
    const breaks = jenksBreaks([1, 2, 3, 4], 20);
    expect(breaks.length).toBeLessThanOrEqual(3);
    for (let i = 1; i < breaks.length; i++) {
      expect(breaks[i]).toBeGreaterThan(breaks[i - 1]);
    }
  });
});

describe('stdDevBreaks', () => {
  it('returns symmetric mean ± σ-step breaks for an even class count', () => {
    // 4 classes → 3 breaks. Scheme: step = σ, breaks centered on the mean:
    // for k classes the (k-1) breaks are mean + σ*(i - (k-1)/2), i = 0..k-2.
    // k=4 → offsets [-1, 0, +1] → [40, 50, 60].
    expect(stdDevBreaks(50, 10, 4)).toEqual([40, 50, 60]);
  });

  it('returns mean-centered breaks for an odd class count', () => {
    // k=5 → 4 breaks, offsets [-1.5, -0.5, +0.5, +1.5] → [35, 45, 55, 65].
    expect(stdDevBreaks(50, 10, 5)).toEqual([35, 45, 55, 65]);
  });

  it('returns a single break at the mean for 2 classes', () => {
    // k=2 → 1 break, offset [0] → [50].
    expect(stdDevBreaks(50, 10, 2)).toEqual([50]);
  });

  it('returns [] for classCount < 2', () => {
    expect(stdDevBreaks(50, 10, 1)).toEqual([]);
  });

  it('returns [] when stddev is not a positive finite number', () => {
    expect(stdDevBreaks(50, 0, 4)).toEqual([]);
    expect(stdDevBreaks(50, Number.NaN, 4)).toEqual([]);
  });

  it('rounds breaks to 2 decimals', () => {
    // mean 0, σ 3.333, k=4 → offsets [-1,0,1] → [-3.33, 0, 3.33].
    expect(stdDevBreaks(0, 3.333, 4)).toEqual([-3.33, 0, 3.33]);
  });
});

describe('manualBreaks', () => {
  it('passes through a strictly ascending array unchanged', () => {
    expect(manualBreaks([1, 5, 10])).toEqual([1, 5, 10]);
  });

  it('dedupes equal adjacent values into a strictly ascending array', () => {
    expect(manualBreaks([5, 5, 10])).toEqual([5, 10]);
  });

  it('throws on a non-ascending (out-of-order) array', () => {
    expect(() => manualBreaks([5, 1, 10])).toThrow();
  });

  it('throws when a value is not finite', () => {
    expect(() => manualBreaks([1, Number.NaN, 3])).toThrow();
  });

  it('returns [] for an empty input', () => {
    expect(manualBreaks([])).toEqual([]);
  });
});
