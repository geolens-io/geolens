import { aggregateStat, configKeys, isColumnName, isStatistic, type Statistic } from '../aggregate';
import { isTextColumn } from '@/lib/column-utils';
import { defineWidget } from '../contract';
import { BarChartFallback } from './BarChartFallback';

// A unique identifier makes every bar 1, so a new chart avoids one when it can.
const IDENTIFIER = /^(id|gid|fid|uuid|globalid|objectid)$|_id$/i;

export interface BarChartConfig {
  /** The column whose values become bars. */
  column: string;
  stat: Statistic;
  /** The column the statistic reads for each bar; null for count. */
  stat_column: string | null;
  /** How many bars, largest first: 1 to 50. */
  limit: number;
}

function parseBarChartConfig(config: unknown): BarChartConfig | null {
  if (!configKeys(config, ['column', 'stat', 'stat_column', 'limit'])) return null;
  const {
    column,
    stat = 'count',
    stat_column = null,
    limit = 10,
  } = config as Record<string, unknown>;
  if (!isColumnName(column) || !isStatistic(stat)) return null;
  if (stat === 'count' ? stat_column !== null : !isColumnName(stat_column)) return null;
  if (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > 50) return null;
  return { column, stat, stat_column: stat_column as string | null, limit: limit as number };
}

export const barChartWidget = defineWidget<BarChartConfig>({
  type: 'bar_chart',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.bar_chart.label',
  i18nKeys: [
    'noData',
    'noRows',
    'showTable',
    'stats.count',
    'stats.sum',
    'stats.mean',
    'stats.min',
    'stats.max',
    'types.bar_chart.summary',
    'types.bar_chart.roleDescription',
    'types.bar_chart.keyboardHint',
    'types.bar_chart.bar',
    'types.bar_chart.noValue',
    'types.bar_chart.other',
  ],
  // `name` is a placeholder: a chart added in the Builder takes its column from
  // initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { column: 'name', stat: 'count', stat_column: null, limit: 10 },
  initialConfig: (columns) => {
    const text = columns.filter((column) => isTextColumn(column.type));
    const category = text.find((column) => !IDENTIFIER.test(column.name)) ?? text[0] ?? columns[0];
    return category ? { column: category.name } : {};
  },
  parseConfig: parseBarChartConfig,
  dataRequest: (config) =>
    config.stat === 'count' || config.stat_column === null
      ? { op: 'value_counts', column: config.column, limit: config.limit }
      : {
          op: 'group_by',
          group_column: config.column,
          stat: aggregateStat(config.stat),
          column: config.stat_column,
          limit: config.limit,
        },
  readsColumns: (config) => [
    { name: config.column, numeric: false },
    ...(config.stat === 'count' || config.stat_column === null
      ? []
      : [{ name: config.stat_column, numeric: true }]),
  ],
  loadRenderer: () => import('./BarChartRenderer'),
  loadEditor: () => import('./BarChartEditor'),
  Fallback: BarChartFallback,
});
