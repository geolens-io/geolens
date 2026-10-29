import { configKeys, isColumnName } from '../aggregate';
import { defineWidget } from '../contract';
import { categoryColumn } from '../initial-columns';
import { CategorySelectorFallback } from './CategorySelectorFallback';

/** The most frequent values a selector offers; the rest count as other values. */
export const SELECTOR_OPTIONS = 20;

export interface CategorySelectorConfig {
  /** The column whose values the reader picks from. */
  column: string;
  /** Whether the reader can pick more than one value. */
  multiple: boolean;
}

function parseCategorySelectorConfig(config: unknown): CategorySelectorConfig | null {
  if (!configKeys(config, ['column', 'multiple'])) return null;
  const { column, multiple = true } = config as Record<string, unknown>;
  if (!isColumnName(column) || typeof multiple !== 'boolean') return null;
  return { column, multiple };
}

export const categorySelectorWidget = defineWidget<CategorySelectorConfig>({
  type: 'category_selector',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.category_selector.label',
  i18nKeys: [
    'noData',
    'noRows',
    'picked',
    'noValue',
    'other',
    'stats.count',
    'types.category_selector.summary',
    'types.category_selector.all',
    'types.category_selector.other',
  ],
  // `name` is a placeholder: a selector added in the Builder takes its column
  // from initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { column: 'name', multiple: true },
  initialConfig: categoryColumn,
  parseConfig: parseCategorySelectorConfig,
  dataRequest: (config) => ({ op: 'value_counts', column: config.column, limit: SELECTOR_OPTIONS }),
  picksColumn: (config) => config.column,
  readsColumns: (config) => [{ name: config.column, numeric: false }],
  loadRenderer: () => import('./CategorySelectorRenderer'),
  loadEditor: () => import('./CategorySelectorEditor'),
  Fallback: CategorySelectorFallback,
});
