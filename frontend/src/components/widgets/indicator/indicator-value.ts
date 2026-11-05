import { useTranslation } from 'react-i18next';
import i18n from '@/i18n/i18n';
import { formatNumber } from '@/lib/format';
import { aggregateResult, aggregateStat, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel } from '../contract';
import type { IndicatorConfig } from './definition';

type Direction = 'above' | 'below' | 'same';
type Tone = 'good' | 'bad' | 'neutral';

interface Difference {
  /** The signed difference; a bigint when the value is an exact integer past 2^53, null when it overflows. */
  amount: number | bigint | null;
  /** Change as a fraction of the reference's size; null when the reference is 0 or the change overflows. */
  percent: number | null;
  direction: Direction;
  tone: Tone;
}

const DECIMAL_TEXT = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;

/**
 * The value as a number, or null when it is missing, not numeric, or a text
 * the number can't hold. The endpoint sends such a decimal as text, and past
 * 2^53 its rounding could hide a real difference.
 */
function numericValue(value: number | string | null | undefined): number | null {
  if (typeof value === 'string') {
    if (!DECIMAL_TEXT.test(value)) return null;
    const number = Number(value);
    return Number.isFinite(number) && Math.abs(number) < 2 ** 53 ? number : null;
  }
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * How `value` differs from the config's reference, or null without a
 * reference, a numeric value, or a difference the comparison can show.
 * A reference of 0 has no percent change.
 */
export function indicatorDifference(
  value: number | string | null | undefined,
  config: IndicatorConfig,
): Difference | null {
  const { reference } = config;
  if (reference === undefined) return null;
  let amount: number | bigint | null;
  let percent: number | null;
  let direction: Direction;
  if (typeof value === 'string' && /^-?\d+$/.test(value) && !Number.isSafeInteger(Number(value))) {
    // An exact integer past 2^53: a Number would round it and could report a false tie.
    if (!Number.isInteger(reference)) return null;
    const exact = BigInt(value) - BigInt(reference);
    amount = exact;
    percent = reference === 0 ? null : Number(exact) / Math.abs(reference);
    direction = exact > 0n ? 'above' : exact < 0n ? 'below' : 'same';
  } else {
    const current = numericValue(value);
    if (current === null) return null;
    const raw = current - reference;
    amount = Number.isFinite(raw) ? raw : null;
    // The quotient form still works when the subtraction overflows.
    percent = reference === 0 ? null : amount === null ? current / Math.abs(reference) - Math.sign(reference) : amount / Math.abs(reference);
    direction = current > reference ? 'above' : current < reference ? 'below' : 'same';
  }
  if (percent !== null && !Number.isFinite(percent)) percent = null;
  const comparison = config.comparison ?? 'both';
  const showsAmount = amount !== null && (comparison !== 'percent' || percent === null);
  if (!showsAmount && (comparison === 'value' || percent === null)) return null;
  const higherIsBetter = config.higher_is_better ?? true;
  return {
    amount,
    percent,
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
    const comparison = config.comparison ?? 'both';
    const amount =
      difference.amount !== null && (comparison !== 'percent' || difference.percent === null)
        ? new Intl.NumberFormat(i18n.language, { ...signed, maximumFractionDigits: 2 }).format(difference.amount)
        : null;
    const percent =
      comparison !== 'value' && difference.percent !== null
        ? formatNumber(difference.percent, { ...signed, style: 'percent', maximumFractionDigits: 1 })
        : null;
    const shown = amount !== null && percent !== null ? `${amount} (${percent})` : (amount ?? percent ?? '');
    const phrase = t(`types.indicator.${difference.direction}`, { amount: shown, label });
    text.difference = {
      arrow: ARROWS[difference.direction],
      tone: difference.tone,
      text:
        difference.tone === 'neutral'
          ? phrase
          : t('types.indicator.outcome', { difference: phrase, outcome: t(`types.indicator.${difference.tone}`) }),
    };
  }
  return text;
}
