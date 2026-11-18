import {
  aggregateStat,
  configKeys,
  isColumnName,
  isStatistic,
  type Statistic,
} from '../aggregate';
import { defineWidget } from '../contract';
import { categoryColumn } from '../initial-columns';
import { TableFallback } from './TableFallback';

export const MAX_TABLE_STATS = 5;
export const MAX_TABLE_ROWS = 50;

interface TableStat {
  stat: Statistic;
  /** The numeric column the statistic reads; null for count. */
  column: string | null;
}

export interface TableConfig {
  /** The column whose values become rows. */
  group_column: string;
  /** One column of numbers per statistic: 1 to 5. */
  stats: TableStat[];
  /** The index in `stats` the rows are ordered by; null orders them by the group value. */
  sort_by: number | null;
  sort: 'asc' | 'desc';
  /** How many rows: 1 to 50. */
  limit: number;
}

function parseStat(raw: unknown): TableStat | null {
  if (!configKeys(raw, ['stat', 'column'])) return null;
  const { stat, column = null } = raw as Record<string, unknown>;
  if (!isStatistic(stat)) return null;
  if (stat === 'count' ? column !== null : !isColumnName(column)) return null;
  return { stat, column: column as string | null };
}

function parseTableConfig(config: unknown): TableConfig | null {
  if (!configKeys(config, ['group_column', 'stats', 'sort_by', 'sort', 'limit'])) return null;
  const { group_column, stats, sort_by = null, sort = 'desc', limit = 10 } = config as Record<string, unknown>;
  if (!isColumnName(group_column)) return null;
  if (!Array.isArray(stats) || stats.length < 1 || stats.length > MAX_TABLE_STATS) return null;
  const parsed = stats.map(parseStat);
  if (parsed.some((stat) => stat === null)) return null;
  if (sort_by !== null && (!Number.isInteger(sort_by) || (sort_by as number) < 0 || (sort_by as number) >= stats.length)) {
    return null;
  }
  if (sort !== 'asc' && sort !== 'desc') return null;
  if (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > MAX_TABLE_ROWS) return null;
  return {
    group_column,
    stats: parsed as TableStat[],
    sort_by: sort_by as number | null,
    sort,
    limit: limit as number,
  };
}

export const tableWidget = defineWidget<TableConfig>({
  type: 'table',
  v: 2,
  storedVersion: () => 1,
  filterVersion: 2,
  surfaces: ['dashboard'],
  labelKey: 'types.table.label',
  i18nKeys: [
    'noData',
    'noRows',
    'picked',
    'noValue',
    'stats.count',
    'stats.sum',
    'stats.mean',
    'stats.min',
    'stats.max',
    'types.table.summary',
    'types.table.truncated_one',
    'types.table.truncated_many',
    'types.table.truncated_other',
  ],
  // `name` is a placeholder: a table added in the Builder takes its column from
  // initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: {
    group_column: 'name',
    stats: [{ stat: 'count', column: null }],
    sort_by: 0,
    sort: 'desc',
    limit: 10,
  },
  initialConfig: (columns) => {
    const { column } = categoryColumn(columns);
    return column ? { group_column: column } : {};
  },
  parseConfig: parseTableConfig,
  heading: (config, t, columnLabel) => t('types.table.summary', { column: columnLabel(config.group_column) }),
  dataRequest: (config) => ({
    op: 'group_by',
    group_column: config.group_column,
    blank_text_as_null: true,
    stats: config.stats.map(({ stat, column }) => ({
      stat: aggregateStat(stat),
      ...(column === null ? {} : { column }),
    })),
    sort_by: config.sort_by ?? 'group',
    sort: config.sort,
    limit: config.limit,
  }),
  picksColumn: (config) => config.group_column,
  readsColumns: (config) => [
    { name: config.group_column, numeric: false },
    ...config.stats.flatMap(({ column }) => (column === null ? [] : [{ name: column, numeric: true }])),
  ],
  loadRenderer: () => import('./TableRenderer'),
  loadEditor: () => import('./TableEditor'),
  Fallback: TableFallback,
});
