import { aggregateStat, configKeys, isColumnName, isStatistic, type Statistic } from '../aggregate';
import { defineWidget } from '../contract';
import { IndicatorFallback } from './IndicatorFallback';

export interface IndicatorConfig {
  stat: Statistic;
  /** The column the statistic reads; null for count. */
  column: string | null;
}

function parseIndicatorConfig(config: unknown): IndicatorConfig | null {
  if (!configKeys(config, ['stat', 'column'])) return null;
  const { stat, column = null } = config as { stat?: unknown; column?: unknown };
  if (!isStatistic(stat)) return null;
  if (stat === 'count' ? column !== null : !isColumnName(column)) return null;
  return { stat, column: column as string | null };
}

export const indicatorWidget = defineWidget<IndicatorConfig>({
  type: 'indicator',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.indicator.label',
  i18nKeys: [
    'noData',
    'stats.count',
    'stats.sum',
    'stats.mean',
    'stats.min',
    'stats.max',
    'types.indicator.summary',
  ],
  defaultConfig: { stat: 'count', column: null },
  parseConfig: parseIndicatorConfig,
  dataRequest: (config) =>
    config.stat === 'count' || config.column === null
      ? { op: 'count' }
      : { op: 'stats', column: config.column, stats: [aggregateStat(config.stat)] },
  readsColumns: (config) =>
    config.stat === 'count' || config.column === null ? [] : [{ name: config.column, numeric: true }],
  loadRenderer: () => import('./IndicatorRenderer'),
  loadEditor: () => import('./IndicatorEditor'),
  Fallback: IndicatorFallback,
});
