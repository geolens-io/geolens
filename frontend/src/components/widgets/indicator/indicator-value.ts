import { useTranslation } from 'react-i18next';
import { formatNumber } from '@/lib/format';
import { aggregateResult, aggregateStat, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel } from '../contract';
import type { IndicatorConfig } from './definition';

type Direction = 'above' | 'below' | 'same';
type Tone = 'good' | 'bad' | 'neutral';

interface Difference {
  amount: number;
  /** Change as a fraction of the reference's size; null when the reference is 0. */
  percent: number | null;
  direction: Direction;
  tone: Tone;
}

/** The value as a number, or null when it is missing or not numeric. */
function numericValue(value: number | string | null | undefined): number | null {
  const number = typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
  return typeof number === 'number' && Number.isFinite(number) ? number : null;
}

/**
 * How `value` differs from the config's reference, or null without a
 * reference or a numeric value. A reference of 0 has no percent change.
 */
export function indicatorDifference(
  value: number | string | null | undefined,
  config: IndicatorConfig,
): Difference | null {
  const current = numericValue(value);
  if (config.reference === undefined || current === null) return null;
  const amount = current - config.reference;
  const direction: Direction = amount > 0 ? 'above' : amount < 0 ? 'below' : 'same';
  const higherIsBetter = config.higher_is_better ?? true;
  return {
    amount,
    percent: config.reference === 0 ? null : amount / Math.abs(config.reference),
    direction,
    tone: direction === 'same' ? 'neutral' : (direction === 'above') === higherIsBetter ? 'good' : 'bad',
  };
}

const ARROWS: Record<Direction, string> = { above: '▲', below: '▼', same: '=' };

interface IndicatorText {
  label: string;
  value: string;
  /** The reference as a line of its own, when the config has one. */
  reference?: { label: string; line: string; value: string };
  /** The difference, once the value is known. */
  difference?: { arrow: string; text: string; tone: Tone };
}

/** The statistic's label and its value as text, with "no data" before the host has fetched it. */
export function useIndicatorText(
  config: IndicatorConfig,
  data: unknown,
  columnLabel: ColumnLabel = columnName,
): IndicatorText {
  const { t } = useTranslation('widgets');
  let value: number | string | null | undefined;
  if (config.stat === 'count') {
    value = aggregateResult(data, 'count')?.count;
  } else {
    const stat = aggregateStat(config.stat) as 'sum' | 'avg' | 'min' | 'max';
    value = aggregateResult(data, 'stats')?.[stat];
  }
  const text: IndicatorText = {
    label: t(STAT_LABEL_KEYS[config.stat], { column: config.column && columnLabel(config.column) }),
    value: value === undefined ? t('noData') : formatAggregateValue(value),
  };
  if (config.reference === undefined) return text;

  const label = config.reference_label ?? t('types.indicator.referenceDefault');
  const referenceValue = formatAggregateValue(config.reference);
  text.reference = { label, value: referenceValue, line: t('types.indicator.reference', { label, value: referenceValue }) };
  const difference = indicatorDifference(value, config);
  if (difference) {
    const signed = { signDisplay: 'exceptZero' } as const;
    const parts: string[] = [];
    const comparison = config.comparison ?? 'both';
    if (comparison !== 'percent' || difference.percent === null) {
      parts.push(formatNumber(difference.amount, { ...signed, maximumFractionDigits: 2 }));
    }
    if (comparison !== 'value' && difference.percent !== null) {
      const percent = formatNumber(difference.percent, { ...signed, style: 'percent', maximumFractionDigits: 1 });
      parts.push(comparison === 'both' ? `(${percent})` : percent);
    }
    text.difference = {
      arrow: ARROWS[difference.direction],
      tone: difference.tone,
      text: t(`types.indicator.${difference.direction}`, { amount: parts.join(' '), label }),
    };
  }
  return text;
}
