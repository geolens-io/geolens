import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { aggregateResult, aggregateStat, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel, type SelectionValue, type ValueLabel, type WidgetSelection } from '../contract';
import { selectedValues } from '../selection';
import { categoryLabel, categoryTableLabel, labelOfColumn, useCategoryRows, type CategoryRow, type CategoryRows } from '../value-counts';
import { pickedColumn, type BarChartConfig, type DateBucket } from './definition';

export interface BarChartText extends CategoryRows {
  /** What the chart shows, e.g. "Count by Land use". */
  summary: string;
  /** What each bar stands for: the grouped column, the field, or the date's column and its time zone. */
  labelHeader: string;
  valueHeader: string;
  /** Said under the chart when the layer has more bars than it lists. */
  note?: string;
}

const NO_ROWS: CategoryRows = {};

/** A bucket's UTC start, written for its span; the key as sent when it isn't a date. */
function bucketLabel(key: SelectionValue, bucket: DateBucket, t: TFunction<'widgets'>, locale: string): string {
  if (typeof key !== 'string' || key.trim() === '') return categoryLabel(key, t);
  const start = new Date(key);
  if (Number.isNaN(start.getTime())) return key;
  const options: Record<DateBucket, Intl.DateTimeFormatOptions> = {
    day: { dateStyle: 'medium' },
    week: { dateStyle: 'medium' },
    month: { year: 'numeric', month: 'short' },
    year: { year: 'numeric' },
  };
  return new Intl.DateTimeFormat(locale, { ...options[bucket], timeZone: 'UTC' }).format(start);
}

function bar(
  key: SelectionValue,
  label: string,
  value: number | string | boolean | null,
  tableLabel?: string,
): CategoryRow {
  return {
    key,
    label,
    tableLabel,
    text: formatAggregateValue(typeof value === 'boolean' ? String(value) : value),
    amount: typeof value === 'boolean' || value === null ? Number.NaN : Number(value),
  };
}

/** The bars of a chart's aggregate result, labelled in the reader's locale. */
export function useBarChartText(
  config: BarChartConfig,
  data: unknown,
  columnLabel: ColumnLabel = columnName,
  valueLabel?: ValueLabel,
): BarChartText {
  const { t, i18n } = useTranslation('widgets');
  const categories = useCategoryRows(data, 'column' in config ? labelOfColumn(valueLabel, config.column) : undefined);

  if (config.mode === 'by_feature') {
    const valueHeader = columnLabel(config.value_column);
    const labelHeader = columnLabel(config.label_column);
    const result = aggregateResult(data, 'rows');
    // A feature list sharing this request may have loaded more pages than the chart shows.
    const shown = result?.rows.slice(0, config.limit);
    return {
      summary: t('types.bar_chart.summaryFeature', { value: valueHeader, label: labelHeader }),
      labelHeader,
      valueHeader,
      rows: shown?.map((row) => {
        const key = row.values[config.label_column] ?? null;
        const labelOf = labelOfColumn(valueLabel, config.label_column);
        return bar(
          key,
          categoryLabel(key, t, labelOf),
          row.values[config.value_column] ?? null,
          categoryTableLabel(key, t, labelOf),
        );
      }),
      note:
        result && shown && (result.has_more || result.rows.length > shown.length)
          ? t('types.bar_chart.moreFeatures', { shown: shown.length })
          : undefined,
    };
  }

  if (config.mode === 'by_fields') {
    const valueHeader = t(`editor.statNames.${config.stat}`);
    const result = aggregateResult(data, 'stats_by_fields');
    return {
      summary: t('types.bar_chart.summaryFields', { stat: valueHeader }),
      labelHeader: t('types.bar_chart.fieldHeader'),
      valueHeader,
      rows: result?.fields.map(({ column, stats }) => bar(column, columnLabel(column), stats[aggregateStat(config.stat)] ?? null)),
    };
  }

  const valueHeader = t(STAT_LABEL_KEYS[config.stat], {
    column: config.stat_column && columnLabel(config.stat_column),
  });
  const column = columnLabel(config.column);

  if (config.mode === 'date') {
    const groups = aggregateResult(data, 'group_by');
    return {
      summary: t('types.bar_chart.summaryDate', {
        stat: valueHeader,
        bucket: t(`types.bar_chart.buckets.${config.date_bucket}`),
      }),
      labelHeader: column,
      valueHeader,
      ...(groups
        ? {
            rows: groups.groups.map((group) =>
              bar(group.key ?? null, bucketLabel(group.key ?? null, config.date_bucket, t, i18n.language), group.value ?? null),
            ),
          }
        : NO_ROWS),
      note: groups?.truncated ? t('types.bar_chart.moreBuckets', { shown: groups.groups.length }) : undefined,
    };
  }

  return {
    summary: t('types.bar_chart.summary', { stat: valueHeader, column }),
    labelHeader: column,
    valueHeader,
    ...categories,
  };
}

/** The props of the chart's `ValueTable`, with the reader's picks marked. */
export function barTableProps(
  config: BarChartConfig,
  text: BarChartText,
  selection: WidgetSelection | null | undefined,
) {
  const column = pickedColumn(config);
  const picked = column === null ? [] : selectedValues(selection, column);
  return {
    caption: text.summary,
    labelHeader: text.labelHeader,
    valueHeader: text.valueHeader,
    rows: text.rows?.map((row) => ({ ...row, picked: picked.includes(row.key) })),
    other: text.other,
  };
}
