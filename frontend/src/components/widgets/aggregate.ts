import i18n from '@/i18n/i18n';
import { formatNumber } from '@/lib/format';
import type { components } from '@/types/api.generated';

/** A dashboard widget's statistic, as `widgets/schemas.py` stores it. */
export type Statistic = 'count' | 'sum' | 'mean' | 'min' | 'max';

const STATISTICS: readonly Statistic[] = ['count', 'sum', 'mean', 'min', 'max'];

/** The aggregate endpoint calls the mean `avg`. */
export function aggregateStat(stat: Statistic): 'count' | 'sum' | 'avg' | 'min' | 'max' {
  return stat === 'mean' ? 'avg' : stat;
}

export function isStatistic(value: unknown): value is Statistic {
  return STATISTICS.includes(value as Statistic);
}

/** The server's `ColumnName`: 1 to 63 characters, PostgreSQL's identifier limit. */
export function isColumnName(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && [...value].length <= 63;
}

/** The keys of `config`, which must all be in `allowed`; null when `config` isn't an object. */
export function configKeys(config: unknown, allowed: readonly string[]): string[] | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  const keys = Object.keys(config);
  return keys.every((key) => allowed.includes(key)) ? keys : null;
}

/** `widgets` keys naming each statistic, with `{{column}}` for all but count. */
export const STAT_LABEL_KEYS = {
  count: 'stats.count',
  sum: 'stats.sum',
  mean: 'stats.mean',
  min: 'stats.min',
  max: 'stats.max',
} as const satisfies Record<Statistic, string>;

type AggregateResponse =
  | components['schemas']['CountResponse']
  | components['schemas']['StatsResponse']
  | components['schemas']['ValueCountsResponse']
  | components['schemas']['HistogramResponse']
  | components['schemas']['GroupByResponse'];

type AggregateResults = { [R in AggregateResponse as R['op']]: R['result'] };

/** The `result` of an aggregate response for `op`, or undefined for anything else. */
export function aggregateResult<Op extends keyof AggregateResults>(
  data: unknown,
  op: Op,
): AggregateResults[Op] | undefined {
  if (typeof data !== 'object' || data === null || (data as { op?: unknown }).op !== op) {
    return undefined;
  }
  return (data as { result: AggregateResults[Op] }).result;
}

/**
 * An exact aggregate value in the reader's locale. The endpoint sends a number
 * JSON can't carry exactly, such as an integer past 2^53, as text.
 */
export function formatAggregateValue(value: number | string | null | undefined): string {
  if (typeof value === 'number') return formatNumber(value, { maximumFractionDigits: 2 });
  if (typeof value === 'string') {
    return /^-?\d+$/.test(value) ? new Intl.NumberFormat(i18n.language).format(BigInt(value)) : value;
  }
  return formatNumber(value);
}
