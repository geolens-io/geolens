import { configKeys, isColumnName } from '../aggregate';
import { defineWidget } from '../contract';
import { numericColumn } from '../initial-columns';
import { HistogramFallback } from './HistogramFallback';

export const MIN_BINS = 2;
export const MAX_BINS = 50;

export interface HistogramConfig {
  /** The numeric column whose values are binned. */
  column: string;
  /** How many equal-width bins span the values: 2 to 50. */
  bins: number;
}

function parseHistogramConfig(config: unknown): HistogramConfig | null {
  if (!configKeys(config, ['column', 'bins'])) return null;
  const { column, bins = 20 } = config as Record<string, unknown>;
  if (!isColumnName(column)) return null;
  if (!Number.isInteger(bins) || (bins as number) < MIN_BINS || (bins as number) > MAX_BINS) return null;
  return { column, bins: bins as number };
}

export const histogramWidget = defineWidget<HistogramConfig>({
  type: 'histogram',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.histogram.label',
  i18nKeys: [
    'noData',
    'noRows',
    'showTable',
    'picked',
    'stats.count',
    'types.histogram.summary',
    'types.histogram.roleDescription',
    'types.histogram.keyboardHint',
    'types.histogram.keyboardHintPick',
    'types.histogram.bin',
    'types.histogram.range',
    'types.histogram.rangeHeader',
  ],
  // `value` is a placeholder: a histogram added in the Builder takes a numeric
  // column from initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { column: 'value', bins: 20 },
  initialConfig: numericColumn,
  parseConfig: parseHistogramConfig,
  dataRequest: (config) => ({ op: 'histogram', column: config.column, bins: config.bins }),
  picksColumn: (config) => config.column,
  readsColumns: (config) => [{ name: config.column, numeric: true }],
  loadRenderer: () => import('./HistogramRenderer'),
  loadEditor: () => import('./HistogramEditor'),
  Fallback: HistogramFallback,
});
