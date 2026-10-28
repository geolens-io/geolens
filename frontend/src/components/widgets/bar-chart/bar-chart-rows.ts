import { useTranslation } from 'react-i18next';
import { aggregateResult, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import type { BarChartConfig } from './definition';

interface BarRow {
  label: string;
  /** The exact value as text, for the table and the readout. */
  text: string;
  /** The value as a number for drawing; NaN when it has none. */
  amount: number;
}

export interface BarChartText {
  /** What the chart shows, e.g. "Count by land_use". */
  summary: string;
  valueHeader: string;
  /** Undefined before the host has fetched the data. */
  rows?: BarRow[];
  /** Rows a top-N count leaves out, as text; undefined when there are none. */
  other?: string;
}

/** The bars of a chart's aggregate result, labelled in the reader's locale. */
export function useBarChartText(config: BarChartConfig, data: unknown): BarChartText {
  const { t } = useTranslation('widgets');
  const valueHeader = t(STAT_LABEL_KEYS[config.stat], { column: config.stat_column });
  const summary = t('types.bar_chart.summary', { stat: valueHeader, column: config.column });
  // A numeric category, such as a year or a code, reads best as stored.
  const row = (key: string | number | boolean | null, value: number | string | null): BarRow => ({
    label: key === null ? t('types.bar_chart.noValue') : String(key),
    text: formatAggregateValue(value),
    amount: value === null ? Number.NaN : Number(value),
  });

  const counts = aggregateResult(data, 'value_counts');
  if (counts) {
    return {
      summary,
      valueHeader,
      rows: counts.values.map((entry) => row(entry.value ?? null, entry.count)),
      other: counts.other_count > 0 ? formatAggregateValue(counts.other_count) : undefined,
    };
  }
  const groups = aggregateResult(data, 'group_by');
  if (groups) {
    return {
      summary,
      valueHeader,
      rows: groups.groups.map((group) => row(group.key ?? null, group.value ?? null)),
    };
  }
  return { summary, valueHeader };
}
