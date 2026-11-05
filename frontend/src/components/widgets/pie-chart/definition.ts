import { aggregateStat, configKeys, isColumnName, isStatistic, STAT_LABEL_KEYS, type Statistic } from '../aggregate';
import { defineWidget } from '../contract';
import { categoryColumn } from '../initial-columns';
import { PieChartFallback } from './PieChartFallback';

export const MAX_SLICES = 50;

export interface PieChartConfig {
  /** The column whose values become slices. */
  column: string;
  stat: Statistic;
  /** The column the statistic reads for each slice; null for count. */
  stat_column: string | null;
  /** How many slices, largest first, before the rest merge into Other: 1 to 50. */
  limit: number;
  /** Colour slices as the layer does when `column` is its style column. */
  use_layer_colors: boolean;
}

function parsePieChartConfig(config: unknown): PieChartConfig | null {
  if (!configKeys(config, ['column', 'stat', 'stat_column', 'limit', 'use_layer_colors'])) return null;
  const {
    column,
    stat = 'count',
    stat_column = null,
    limit = 10,
    use_layer_colors = true,
  } = config as Record<string, unknown>;
  if (!isColumnName(column) || !isStatistic(stat)) return null;
  if (stat === 'count' ? stat_column !== null : !isColumnName(stat_column)) return null;
  if (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > MAX_SLICES) return null;
  if (typeof use_layer_colors !== 'boolean') return null;
  return { column, stat, stat_column: stat_column as string | null, limit: limit as number, use_layer_colors };
}

export const pieChartWidget = defineWidget<PieChartConfig>({
  type: 'pie_chart',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.pie_chart.label',
  i18nKeys: [
    'noData',
    'noRows',
    'showTable',
    'picked',
    'noValue',
    'other',
    'stats.count',
    'stats.sum',
    'stats.mean',
    'stats.min',
    'stats.max',
    'types.pie_chart.summary',
    'types.pie_chart.roleDescription',
    'types.pie_chart.keyboardHint',
    'types.pie_chart.keyboardHintPick',
    'types.pie_chart.keyboardHintPickPage',
    'types.pie_chart.slice',
  ],
  // `name` is a placeholder: a chart added in the Builder takes its column from
  // initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { column: 'name', stat: 'count', stat_column: null, limit: 10, use_layer_colors: true },
  initialConfig: categoryColumn,
  parseConfig: parsePieChartConfig,
  heading: (config, t, columnLabel) =>
    t('types.pie_chart.summary', {
      stat: t(STAT_LABEL_KEYS[config.stat], { column: config.stat_column && columnLabel(config.stat_column) }),
      column: columnLabel(config.column),
    }),
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
  picksColumn: (config) => config.column,
  readsColumns: (config) => [
    { name: config.column, numeric: false },
    ...(config.stat === 'count' || config.stat_column === null
      ? []
      : [{ name: config.stat_column, numeric: true }]),
  ],
  loadRenderer: () => import('./PieChartRenderer'),
  loadEditor: () => import('./PieChartEditor'),
  Fallback: PieChartFallback,
});
