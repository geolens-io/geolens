import { useTranslation } from 'react-i18next';
import { aggregateResult, formatAggregateValue, STAT_LABEL_KEYS } from '../aggregate';
import { columnName, type ColumnLabel, type SelectionValue } from '../contract';
import { categoryLabel } from '../value-counts';
import type { TableConfig } from './definition';

interface TableRow {
  /** The group as the endpoint sent it, which a pick filters on. */
  key: SelectionValue;
  label: string;
  /** Each statistic's exact value as text, in the config's order. */
  texts: string[];
}

export interface TableText {
  /** What the table shows, e.g. "Statistics by Land use". */
  summary: string;
  groupHeader: string;
  /** One header per statistic. */
  statHeaders: string[];
  /** Undefined before the host has fetched the data. */
  rows?: TableRow[];
  /** Whether more groups matched than the table lists. */
  truncated: boolean;
}

/** The rows of a table's group-by result, labelled in the reader's locale. */
export function useTableText(config: TableConfig, data: unknown, columnLabel: ColumnLabel = columnName): TableText {
  const { t } = useTranslation('widgets');
  const groupHeader = columnLabel(config.group_column);
  const result = aggregateResult(data, 'group_by');
  return {
    summary: t('types.table.summary', { column: groupHeader }),
    groupHeader,
    statHeaders: config.stats.map(({ stat, column }) =>
      t(STAT_LABEL_KEYS[stat], { column: column && columnLabel(column) }),
    ),
    rows: result?.groups.map((group) => {
      const values = group.values ?? [group.value];
      return {
        key: group.key ?? null,
        label: categoryLabel(group.key ?? null, t),
        texts: config.stats.map((_, index) => formatAggregateValue(values[index])),
      };
    }),
    truncated: result?.truncated ?? false,
  };
}
