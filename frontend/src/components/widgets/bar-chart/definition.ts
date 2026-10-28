import { aggregateStat, configKeys, isColumnName, isStatistic, type Statistic } from '../aggregate';
import { defineWidget } from '../contract';
import { BarChartFallback } from './BarChartFallback';

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
  // The column must exist on the layer, so an editor picks one before saving.
  defaultConfig: { column: 'name', stat: 'count', stat_column: null, limit: 10 },
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
  loadRenderer: () => import('./BarChartRenderer'),
  Fallback: BarChartFallback,
});
