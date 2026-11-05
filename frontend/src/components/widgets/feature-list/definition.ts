import { isTextColumn } from '@/lib/column-utils';
import { configKeys, isColumnName } from '../aggregate';
import { defineWidget, type WidgetColumn } from '../contract';
import { FeatureListFallback } from './FeatureListFallback';

export interface FeatureListConfig {
  /** The column each row shows as its title. */
  title_column: string;
  /** A second line under the title; null for none. */
  subtitle_column: string | null;
  /** The column the list is ordered by; null orders by feature id. */
  sort_column: string | null;
  sort: 'asc' | 'desc';
  /** Features per page: 10 to 100. */
  page_size: number;
}

export const MIN_PAGE_SIZE = 10;
export const MAX_PAGE_SIZE = 100;

const KEYS = ['title_column', 'subtitle_column', 'sort_column', 'sort', 'page_size'] as const;
// A unique identifier makes a poor title, so a new list avoids one when it can.
const IDENTIFIER = /^(id|gid|fid|uuid|globalid|objectid)$|_id$/i;

function optionalColumn(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return isColumnName(value) ? value : undefined;
}

function parseFeatureListConfig(config: unknown): FeatureListConfig | null {
  if (!configKeys(config, KEYS)) return null;
  const { title_column, subtitle_column, sort_column, sort = 'asc', page_size = 25 } =
    config as Record<string, unknown>;
  const subtitle = optionalColumn(subtitle_column);
  const sortColumn = optionalColumn(sort_column);
  if (!isColumnName(title_column) || subtitle === undefined || sortColumn === undefined) return null;
  if (sort !== 'asc' && sort !== 'desc') return null;
  if (!Number.isInteger(page_size) || (page_size as number) < MIN_PAGE_SIZE || (page_size as number) > MAX_PAGE_SIZE) {
    return null;
  }
  return {
    title_column,
    subtitle_column: subtitle,
    sort_column: sortColumn,
    sort,
    page_size: page_size as number,
  };
}

/** The column a new list titles its rows with: the first text column that isn't an identifier, else the first column. */
function titleColumn(columns: readonly WidgetColumn[]): { title_column?: string } {
  const text = columns.filter((column) => isTextColumn(column.type));
  const pick = text.find((column) => !IDENTIFIER.test(column.name)) ?? text[0] ?? columns[0];
  return pick ? { title_column: pick.name } : {};
}

export const featureListWidget = defineWidget<FeatureListConfig>({
  type: 'feature_list',
  v: 1,
  surfaces: ['dashboard'],
  labelKey: 'types.feature_list.label',
  i18nKeys: [
    'noData',
    'noRows',
    'noValue',
    'types.feature_list.summary',
    'types.feature_list.listLabel',
    'types.feature_list.shown',
    'types.feature_list.shownMore',
    'types.feature_list.loadMore',
    'types.feature_list.loadingMore',
    'types.feature_list.loadFailed',
    'types.feature_list.retryLoadMore',
    'types.feature_list.zoomTo',
    'types.feature_list.noMap',
  ],
  // `name` is a placeholder: a list added in the Builder takes its column from
  // initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { title_column: 'name', subtitle_column: null, sort_column: null, sort: 'asc', page_size: 25 },
  initialConfig: titleColumn,
  parseConfig: parseFeatureListConfig,
  heading: (config, t, columnLabel) =>
    t('types.feature_list.summary', { column: columnLabel(config.title_column) }),
  dataRequest: (config) => ({
    op: 'rows',
    columns: [...new Set([config.title_column, config.subtitle_column, config.sort_column])].filter(
      (column): column is string => column !== null,
    ),
    ...(config.sort_column === null ? {} : { sort_column: config.sort_column }),
    sort: config.sort,
    limit: config.page_size,
  }),
  readsColumns: (config) =>
    [config.title_column, config.subtitle_column, config.sort_column]
      .filter((column): column is string => column !== null)
      .map((name) => ({ name, numeric: false })),
  loadRenderer: () => import('./FeatureListRenderer'),
  loadEditor: () => import('./FeatureListEditor'),
  Fallback: FeatureListFallback,
});
