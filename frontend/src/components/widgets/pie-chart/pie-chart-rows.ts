import { useTranslation } from 'react-i18next';
import { aggregateResult, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel, type WidgetSelection } from '../contract';
import { selectedValues } from '../selection';
import { useCategoryRows, type CategoryRows } from '../value-counts';
import type { PieChartConfig } from './definition';

export interface PieChartText extends CategoryRows {
  /** What the chart shows, e.g. "Count by Land use". */
  summary: string;
  labelHeader: string;
  valueHeader: string;
  /** The rows a count's top-N list leaves out, as a number, for the "Other" slice. */
  otherAmount: number;
}

/** The slices of a chart's aggregate result, labelled in the reader's locale. */
export function usePieChartText(
  config: PieChartConfig,
  data: unknown,
  columnLabel: ColumnLabel = columnName,
): PieChartText {
  const { t } = useTranslation('widgets');
  const valueHeader = t(STAT_LABEL_KEYS[config.stat], {
    column: config.stat_column && columnLabel(config.stat_column),
  });
  const labelHeader = columnLabel(config.column);
  return {
    summary: t('types.pie_chart.summary', { stat: valueHeader, column: labelHeader }),
    labelHeader,
    valueHeader,
    otherAmount: aggregateResult(data, 'value_counts')?.other_count ?? 0,
    ...useCategoryRows(data),
  };
}

/** The props of the chart's `ValueTable`, with the reader's picks marked. */
export function pieTableProps(
  config: PieChartConfig,
  text: PieChartText,
  selection: WidgetSelection | null | undefined,
) {
  const picked = selectedValues(selection, config.column);
  return {
    caption: text.summary,
    labelHeader: text.labelHeader,
    valueHeader: text.valueHeader,
    rows: text.rows?.map((row) => ({ ...row, picked: picked.includes(row.key) })),
    other: text.other,
  };
}
