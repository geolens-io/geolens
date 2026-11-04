import { aggregateStat, configKeys, isColumnName, isStatistic, STAT_LABEL_KEYS, type Statistic } from '../aggregate';
import { defineWidget } from '../contract';
import { IndicatorFallback } from './IndicatorFallback';

export type IndicatorComparison = 'value' | 'percent' | 'both';

export interface IndicatorConfig {
  stat: Statistic;
  /** The column the statistic reads; null for count. */
  column: string | null;
  /** A fixed number the value is compared with. */
  reference?: number;
  /** A short name for the reference; only with a reference. */
  reference_label?: string;
  /** Whether a value above the reference is the good outcome; true when absent. */
  higher_is_better?: boolean;
  /** How the difference is shown; both when absent. */
  comparison?: IndicatorComparison;
}

/** The longest `reference_label` the server accepts. */
export const REFERENCE_LABEL_MAX_LENGTH = 40;

const BASE_KEYS = ['stat', 'column'] as const;
const REFERENCE_KEYS = ['reference', 'reference_label', 'higher_is_better', 'comparison'] as const;

/** Version 2 is the one that may carry the reference options. */
function storedVersion(config: IndicatorConfig): number {
  return REFERENCE_KEYS.some((key) => config[key] !== undefined) ? 2 : 1;
}

function parseReference(raw: Record<string, unknown>): Partial<IndicatorConfig> | null {
  const { reference, reference_label: label, higher_is_better: higher, comparison } = raw;
  if (reference !== undefined && (typeof reference !== 'number' || !Number.isFinite(reference))) return null;
  if (label !== undefined) {
    if (reference === undefined || typeof label !== 'string') return null;
    if (label.length === 0 || [...label].length > REFERENCE_LABEL_MAX_LENGTH) return null;
  }
  if (higher !== undefined && typeof higher !== 'boolean') return null;
  if (comparison !== undefined && comparison !== 'value' && comparison !== 'percent' && comparison !== 'both') {
    return null;
  }
  return {
    ...(reference === undefined ? {} : { reference }),
    ...(label === undefined ? {} : { reference_label: label as string }),
    ...(higher === undefined ? {} : { higher_is_better: higher }),
    ...(comparison === undefined ? {} : { comparison }),
  };
}

function parseIndicatorConfig(config: unknown, v: number): IndicatorConfig | null {
  if (!configKeys(config, v >= 2 ? [...BASE_KEYS, ...REFERENCE_KEYS] : BASE_KEYS)) return null;
  const raw = config as Record<string, unknown>;
  const { stat, column = null } = raw;
  if (!isStatistic(stat)) return null;
  if (stat === 'count' ? column !== null : !isColumnName(column)) return null;
  const reference = parseReference(raw);
  if (reference === null) return null;
  return { stat, column: column as string | null, ...reference };
}

export const indicatorWidget = defineWidget<IndicatorConfig>({
  type: 'indicator',
  v: 2,
  storedVersion,
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
    'types.indicator.reference',
    'types.indicator.referenceDefault',
    'types.indicator.above',
    'types.indicator.below',
    'types.indicator.same',
    'types.indicator.difference',
    'types.indicator.measure',
    'types.indicator.value',
  ],
  defaultConfig: { stat: 'count', column: null },
  parseConfig: parseIndicatorConfig,
  heading: (config, t, columnLabel) =>
    t(STAT_LABEL_KEYS[config.stat], { column: config.column && columnLabel(config.column) }),
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
