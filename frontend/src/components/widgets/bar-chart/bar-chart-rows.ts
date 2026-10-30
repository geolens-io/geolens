import { useTranslation } from 'react-i18next';
import { STAT_LABEL_KEYS } from '../aggregate';
import type { WidgetSelection } from '../contract';
import { selectedValues } from '../selection';
import { useCategoryRows, type CategoryRows } from '../value-counts';
import type { BarChartConfig } from './definition';

export interface BarChartText extends CategoryRows {
  /** What the chart shows, e.g. "Count by land_use". */
  summary: string;
  valueHeader: string;
}

/** The bars of a chart's aggregate result, labelled in the reader's locale. */
export function useBarChartText(config: BarChartConfig, data: unknown): BarChartText {
  const { t } = useTranslation('widgets');
  const valueHeader = t(STAT_LABEL_KEYS[config.stat], { column: config.stat_column });
  return {
    summary: t('types.bar_chart.summary', { stat: valueHeader, column: config.column }),
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
    labelHeader: config.column,
    valueHeader: text.valueHeader,
    rows: text.rows?.map((row) => ({ ...row, picked: picked.includes(row.key) })),
    other: text.other,
  };
}
