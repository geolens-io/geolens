import { useTranslation } from 'react-i18next';
import { STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel, type WidgetSelection } from '../contract';
import { selectedValues } from '../selection';
import { useCategoryRows, type CategoryRows } from '../value-counts';
import type { BarChartConfig } from './definition';

export interface BarChartText extends CategoryRows {
  /** What the chart shows, e.g. "Count by Land use". */
  summary: string;
  /** The grouped column's label. */
  labelHeader: string;
  valueHeader: string;
}

/** The bars of a chart's aggregate result, labelled in the reader's locale. */
export function useBarChartText(
  config: BarChartConfig,
  data: unknown,
  columnLabel: ColumnLabel = columnName,
): BarChartText {
  const { t } = useTranslation('widgets');
  const valueHeader = t(STAT_LABEL_KEYS[config.stat], {
    column: config.stat_column && columnLabel(config.stat_column),
  });
  const labelHeader = columnLabel(config.column);
  return {
    summary: t('types.bar_chart.summary', { stat: valueHeader, column: labelHeader }),
    labelHeader,
    valueHeader,
    ...useCategoryRows(data),
  };
}

/** The props of the chart's `ValueTable`, with the reader's picks marked. */
export function barTableProps(
  config: BarChartConfig,
  text: BarChartText,
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
