/** Round to 2 decimal places — the shared rounding convention for all breaks. */
function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * Compute equal-interval class breaks.
 * Returns classCount - 1 break values evenly spaced between min and max,
 * rounded to 2 decimal places.
 */
export function equalIntervalBreaks(
  min: number,
  max: number,
  classCount: number,
): number[] {
  if (classCount < 2) return [];
  const step = (max - min) / classCount;
  const breaks: number[] = [];
  for (let i = 1; i < classCount; i++) {
    breaks.push(round2(min + step * i));
  }
  return breaks;
}

/**
 * Pass through quantile values from the API (already computed server-side).
 * Thin wrapper for semantic clarity and to keep a consistent module API.
 */
export function quantileBreaks(quantiles: number[]): number[] {
  return quantiles;
}

/**
 * Jenks natural-breaks classification (Fisher-Jenks dynamic programming).
 *
 * Computes `classCount - 1` ascending break values that minimise the
 * within-class variance (maximise the goodness-of-variance-fit) over the
 * supplied `values`. Self-contained — no external dependency.
 *
 * IMPORTANT — input representativeness: this operates on whatever array it is
 * given. When the full raw column is not client-available, callers pass a
 * representative SAMPLE (e.g. the server-computed quantiles) and must label
 * the result honestly in the UI; the breaks are then exact for the sample,
 * not the full column.
 *
 * Contract:
 * - Returns [] when `classCount < 2`.
 * - Falls back to `equalIntervalBreaks(min, max, classCount)` when there are
 *   fewer distinct values than requested classes (Jenks is undefined there).
 * - `classCount` is clamped to the number of available values.
 * - Returned breaks are the lower limits of classes 2..k, ascending and
 *   rounded to 2 decimals.
 */
export function jenksBreaks(values: number[], classCount: number): number[] {
  if (classCount < 2) return [];
  if (values.length === 0) return [];

  const sorted = [...values].filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (sorted.length === 0) return [];

  const min = sorted[0];
  const max = sorted[sorted.length - 1];

  // Degenerate: a single distinct value or no spread — Jenks is undefined, so
  // fall back to equal-interval over [min, max] at the requested class count.
  if (sorted.length < 2 || min === max) {
    return equalIntervalBreaks(min, max, classCount);
  }

  // Clamp class count to the number of available values (asking for more
  // classes than data points is meaningless; Jenks would produce phantom
  // empty classes).
  const k = Math.min(classCount, sorted.length);
  const n = sorted.length;

  // Dynamic-programming matrices (1-indexed for the classic formulation).
  // lowerClassLimits[i][j] = index (1-based) of the start of the last class
  //   when partitioning the first i values into j classes.
  // varianceCombinations[i][j] = the minimised variance for that partition.
  const lowerClassLimits: number[][] = [];
  const varianceCombinations: number[][] = [];
  for (let i = 0; i <= n; i++) {
    lowerClassLimits.push(new Array(k + 1).fill(0));
    varianceCombinations.push(new Array(k + 1).fill(0));
  }

  for (let j = 1; j <= k; j++) {
    lowerClassLimits[1][j] = 1;
    varianceCombinations[1][j] = 0;
    for (let i = 2; i <= n; i++) {
      varianceCombinations[i][j] = Infinity;
    }
  }

  for (let l = 2; l <= n; l++) {
    let sum = 0; // running sum of values
    let sumSquares = 0; // running sum of squared values
    let w = 0; // running count
    let variance = 0;

    for (let m = 1; m <= l; m++) {
      const lowerClassLimit = l - m + 1;
      const val = sorted[lowerClassLimit - 1];

      w += 1;
      sum += val;
      sumSquares += val * val;
      variance = sumSquares - (sum * sum) / w;

      const i4 = lowerClassLimit - 1;
      if (i4 !== 0) {
        for (let j = 2; j <= k; j++) {
          if (
            varianceCombinations[l][j] >=
            variance + varianceCombinations[i4][j - 1]
          ) {
            lowerClassLimits[l][j] = lowerClassLimit;
            varianceCombinations[l][j] =
              variance + varianceCombinations[i4][j - 1];
          }
        }
      }
    }

    lowerClassLimits[l][1] = 1;
    varianceCombinations[l][1] = variance;
  }

  // Backtrack the lower class limits into break values (lower limit of each
  // class except the first). Produces k-1 breaks.
  const breaks: number[] = [];
  let countNum = n;
  for (let j = k; j >= 2; j--) {
    const limitIndex = lowerClassLimits[countNum][j] - 1;
    breaks.push(round2(sorted[limitIndex]));
    countNum = lowerClassLimits[countNum][j] - 1;
  }
  breaks.reverse();

  // Ensure strictly ascending (dedupe) — clustered data can collide.
  return [...new Set(breaks)];
}

/**
 * Standard-deviation classification: breaks at mean ± multiples of σ.
 *
 * Scheme (documented + asserted in tests): for `classCount` classes there are
 * `b = classCount - 1` breaks, one σ-step apart and symmetric about the mean.
 * The i-th break (i = 0..b-1) is:
 *
 *     mean + stddev * (i - (b - 1) / 2)
 *
 * i.e. the breaks are centred so the mean sits exactly at the middle boundary
 * (odd break count) or midway between the two central boundaries (even count):
 * - k=2 (b=1) → [mean]
 * - k=4 (b=3) → [mean-σ, mean, mean+σ]
 * - k=5 (b=4) → [mean-1.5σ, mean-0.5σ, mean+0.5σ, mean+1.5σ]
 *
 * Returns [] for `classCount < 2` or when `stddev` is not a positive finite
 * number (callers must NOT fabricate σ — gate the option upstream instead).
 * Breaks are rounded to 2 decimals.
 */
export function stdDevBreaks(
  mean: number,
  stddev: number,
  classCount: number,
): number[] {
  if (classCount < 2) return [];
  if (!Number.isFinite(stddev) || stddev <= 0 || !Number.isFinite(mean)) {
    return [];
  }
  const b = classCount - 1; // number of breaks
  const breaks: number[] = [];
  for (let i = 0; i < b; i++) {
    const offset = i - (b - 1) / 2;
    breaks.push(round2(mean + stddev * offset));
  }
  return breaks;
}

/**
 * Manual breaks: validate a user-supplied break array.
 *
 * Contract:
 * - Empty input → [].
 * - Equal adjacent values are deduped (so the result is strictly ascending).
 * - Throws if any value is non-finite.
 * - Throws if the (non-equal) values are not in ascending order — a genuine
 *   out-of-order entry is a user error the editor must surface inline, not a
 *   silent reorder (silently sorting would mask a typo and write a misleading
 *   step expression).
 */
export function manualBreaks(userBreaks: number[]): number[] {
  if (userBreaks.length === 0) return [];

  for (const v of userBreaks) {
    if (!Number.isFinite(v)) {
      throw new Error('manualBreaks: all breaks must be finite numbers');
    }
  }

  const out: number[] = [];
  for (let i = 0; i < userBreaks.length; i++) {
    const v = userBreaks[i];
    if (i > 0) {
      const prev = userBreaks[i - 1];
      if (v < prev) {
        throw new Error('manualBreaks: breaks must be in ascending order');
      }
      if (v === prev) continue; // dedupe equal adjacent values
    }
    out.push(v);
  }
  return out;
}
