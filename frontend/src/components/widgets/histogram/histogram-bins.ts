import { useTranslation } from 'react-i18next';
import { isIntegerColumn } from '@/lib/column-utils';
import { formatNumber } from '@/lib/format';
import { aggregateResult, formatAggregateValue } from '../aggregate';
import type { WidgetColumn, WidgetSelection } from '../contract';
import { togglePick } from '../selection';
import type { HistogramConfig } from './definition';

export interface HistogramBinRow {
  lower: number;
  upper: number;
  /** The last bin holds its upper edge, the column's maximum; whole-number bins are half-open. */
  includeUpper: boolean;
  count: number;
  /** The bin's edges and range in the reader's locale. */
  lowerText: string;
  upperText: string;
  label: string;
  countText: string;
}

export interface HistogramText {
  /** What the chart shows, e.g. "Distribution of height". */
  summary: string;
  rangeHeader: string;
  countHeader: string;
  /** Undefined before the host has fetched the data. */
  bins?: HistogramBinRow[];
}

/** Enough decimals that neighbouring edges of bins `width` wide read differently. */
function edgeDigits(width: number): number {
  if (!(width > 0) || !Number.isFinite(width)) return 2;
  return Math.min(6, Math.max(0, Math.ceil(-Math.log10(width)) + 1));
}

/** The bins of a histogram's aggregate result, labelled in the reader's locale. */
export function useHistogramText(
  config: HistogramConfig,
  data: unknown,
  columns?: readonly WidgetColumn[],
): HistogramText {
  const { t } = useTranslation('widgets');
  const headings = {
    summary: t('types.histogram.summary', { column: config.column }),
    rangeHeader: t('types.histogram.rangeHeader'),
    countHeader: t('stats.count'),
  };
  const result = aggregateResult(data, 'histogram');
  if (!result) return headings;
  const integer = isIntegerColumn(columns?.find((column) => column.name === config.column)?.type ?? '');
  const first = result.bins[0];
  const digits = first ? edgeDigits(first.upper - first.lower) : 2;
  const edge = (value: number) => formatNumber(value, { maximumFractionDigits: digits });
  return {
    ...headings,
    bins: result.bins.map((bin, index, all) => {
      // The server bins an integer column in whole numbers, so [a, a + w) holds a to a + w - 1.
      const whole = integer && Number.isInteger(bin.lower) && Number.isInteger(bin.upper);
      const lowerText = edge(bin.lower);
      const upperText = whole ? edge(Math.max(bin.lower, bin.upper - 1)) : edge(bin.upper);
      return {
        lower: bin.lower,
        upper: bin.upper,
        includeUpper: bin.lower === bin.upper || (index === all.length - 1 && !whole),
        count: bin.count,
        lowerText,
        upperText,
        // One value fills a single bin with no width.
        label:
          bin.lower === bin.upper || (whole && bin.upper - bin.lower <= 1)
            ? lowerText
            : t('types.histogram.range', { lower: lowerText, upper: upperText }),
        countText: formatAggregateValue(bin.count),
      };
    }),
  };
}

type Interval = { lower: number; upper: number; includeUpper: boolean };

/** Whether two intervals, each closed below and closed above only when `includeUpper`, share a value. */
function overlaps(a: Interval, b: Interval): boolean {
  const low = Math.max(a.lower, b.lower);
  const high = Math.min(a.upper, b.upper);
  if (low !== high) return low < high;
  return (low < a.upper || a.includeUpper) && (low < b.upper || b.includeUpper);
}

/**
 * Which bins hold values of the picked range. A pick keeps the edges of the
 * bins it was made on; when another widget's pick re-bins this histogram,
 * every bin the range reaches is marked.
 */
export function pickedBins(
  text: HistogramText,
  config: HistogramConfig,
  selection: WidgetSelection | null | undefined,
): boolean[] {
  const range = selection && selection.column === config.column && 'range' in selection ? selection.range : null;
  return (text.bins ?? []).map((bin) => range !== null && overlaps(bin, range));
}

/** What a click on a bin picks: its range, or nothing when the bin is already marked. */
export function pickBin(bin: HistogramBinRow, config: HistogramConfig, marked: boolean): WidgetSelection | null {
  return togglePick(marked, {
    column: config.column,
    label: bin.label,
    range: { lower: bin.lower, upper: bin.upper, includeUpper: bin.includeUpper },
  });
}

/** The props of the histogram's `ValueTable`, with the picked bins marked. */
export function histogramTableProps(
  config: HistogramConfig,
  text: HistogramText,
  selection: WidgetSelection | null | undefined,
) {
  const picked = pickedBins(text, config, selection);
  return {
    caption: text.summary,
    labelHeader: text.rangeHeader,
    valueHeader: text.countHeader,
    rows: text.bins?.map((bin, index) => ({ label: bin.label, text: bin.countText, picked: picked[index] })),
  };
}
