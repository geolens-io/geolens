import { useTranslation } from 'react-i18next';
import i18n from '@/i18n/i18n';
import { formatNumber } from '@/lib/format';
import { aggregateResult, aggregateStat, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel } from '../contract';
import type { IndicatorConfig } from './definition';

type Direction = 'above' | 'below' | 'same';
type Tone = 'good' | 'bad' | 'neutral';

interface Difference {
  /** The signed difference; exact text or a bigint when it came from an exact value, null when it overflows. */
  amount: number | bigint | string | null;
  /** Change as a fraction of the reference's size; null when the reference is 0 or the change overflows. */
  percent: number | null;
  direction: Direction;
  tone: Tone;
}

const DECIMAL_TEXT = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/;
const MAX_TEXT_LENGTH = 300;

/** A decimal as `digits / 10^scale`, so two of them compare without rounding. */
interface Decimal {
  digits: bigint;
  scale: number;
}

function parseDecimal(text: string): Decimal | null {
  const match = text.length <= MAX_TEXT_LENGTH ? DECIMAL_TEXT.exec(text) : null;
  if (!match) return null;
  const fraction = match[3] ?? '';
  const exponent = match[4] === undefined ? 0 : Number(match[4]);
  if (Math.abs(exponent) > MAX_TEXT_LENGTH) return null;
  const digits = BigInt(match[2] + fraction);
  return { digits: match[1] ? -digits : digits, scale: fraction.length - exponent };
}

/** `diff / 10^scale` as exact decimal text, for a formatter that reads text without rounding it. */
function decimalText(diff: bigint, scale: number): string {
  const digits = (diff < 0n ? -diff : diff).toString().padStart(scale + 1, '0');
  const point = digits.length - scale;
  return `${diff < 0n ? '-' : ''}${digits.slice(0, point)}.${digits.slice(point)}`;
}

/**
 * The exact difference between a decimal text and a number, or null when the
 * text is not a plain decimal. The endpoint sends a value as text when a float
 * can't hold it, and rounding it could report a false tie.
 */
function exactDifference(
  text: string,
  reference: number,
): { amount: number | bigint | string; percent: number | null; sign: number } | null {
  const current = parseDecimal(text);
  const other = parseDecimal(String(reference));
  if (!current || !other) return null;
  const scale = Math.max(current.scale, other.scale);
  if (scale > MAX_TEXT_LENGTH) return null;
  const lift = (decimal: Decimal) => decimal.digits * 10n ** BigInt(scale - decimal.scale);
  const diff = lift(current) - lift(other);
  const sign = diff > 0n ? 1 : diff < 0n ? -1 : 0;
  // Both sides are in the same unit, so their ratio needs no scale; it is null when it overflows.
  const size = Math.abs(Number(lift(other)));
  const ratio = Number(diff) / size;
  const percent = other.digits === 0n || !Number.isFinite(ratio) ? null : ratio;
  if (scale <= 0) return { amount: diff * 10n ** BigInt(-scale), percent, sign };
  return { amount: decimalText(diff, scale), percent, sign };
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
  let amount: number | bigint | string | null;
  let percent: number | null;
  let direction: Direction;
  if (typeof value === 'string') {
    const exact = exactDifference(value, reference);
    if (!exact) return null;
    amount = exact.amount;
    percent = exact.percent;
    direction = exact.sign > 0 ? 'above' : exact.sign < 0 ? 'below' : 'same';
  } else {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    const raw = value - reference;
    amount = Number.isFinite(raw) ? raw : null;
    // The quotient form still works when the subtraction overflows.
    percent =
      reference === 0
        ? null
        : amount === null
          ? value / Math.abs(reference) - Math.sign(reference)
          : amount / Math.abs(reference);
    direction = value > reference ? 'above' : value < reference ? 'below' : 'same';
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
  difference?: { arrow: string; text: string; tone: Tone; outcome?: string };
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
  const phraseLabel = config.reference_label ?? t('types.indicator.referenceDefaultPhrase');
  const referenceValue = formatAggregateValue(config.reference);
  text.reference = { label, value: referenceValue, line: t('types.indicator.reference', { label, value: referenceValue }) };
  const difference = indicatorDifference(value, config);
  if (difference) {
    const unsigned = { signDisplay: 'never' } as const;
    const comparison = config.comparison ?? 'both';
    const amount =
      difference.amount !== null && (comparison !== 'percent' || difference.percent === null)
        ? (new Intl.NumberFormat(i18n.language, { ...unsigned, maximumFractionDigits: 2 }).format as (v: unknown) => string)(difference.amount)
        : null;
    const percent =
      comparison !== 'value' && difference.percent !== null
        ? formatNumber(difference.percent, { ...unsigned, style: 'percent', maximumFractionDigits: 1 })
        : null;
    const shown = amount !== null && percent !== null ? `${amount} (${percent})` : (amount ?? percent ?? '');
    const phrase = t(`types.indicator.${difference.direction}`, { amount: shown, label: phraseLabel });
    text.difference = {
      arrow: ARROWS[difference.direction],
      tone: difference.tone,
      text: phrase,
      outcome: difference.tone === 'neutral' ? undefined : t(`types.indicator.${difference.tone}`),
    };
  }
  return text;
}
