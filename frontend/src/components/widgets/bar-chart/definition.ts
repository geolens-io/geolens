import { aggregateStat, configKeys, isColumnName, isStatistic, STAT_LABEL_KEYS, type Statistic } from '../aggregate';
import { defineWidget } from '../contract';
import { categoryColumn } from '../initial-columns';
import { BarChartFallback } from './BarChartFallback';

export const MAX_BARS = 50;
export const MAX_FIELDS = 20;
export const DATE_BUCKETS = ['day', 'week', 'month', 'year'] as const;
export type DateBucket = (typeof DATE_BUCKETS)[number];

/** One bar per value of `column`: the form of every chart stored at version 1. */
export interface CategoryBarChartConfig {
  mode?: 'category';
  /** The column whose values become bars. */
  column: string;
  stat: Statistic;
  /** The column the statistic reads for each bar; null for count. */
  stat_column: string | null;
  /** How many bars, largest first: 1 to 50. */
  limit: number;
  /** Colour bars as the layer does when `column` is its style column; stored only when off. */
  use_layer_colors?: boolean;
}

/** `column` grouped by the UTC day, week, month or year it falls in, in date order. */
export interface DateBarChartConfig {
  mode: 'date';
  column: string;
  date_bucket: DateBucket;
  stat: Statistic;
  stat_column: string | null;
  /** How many buckets, earliest first: 1 to 50. */
  limit: number;
}

/** One bar per feature, labelled by one field and sized by a numeric one. */
export interface FeatureBarChartConfig {
  mode: 'by_feature';
  label_column: string;
  value_column: string;
  /** Bar order by value; `desc` keeps the largest. */
  sort: 'asc' | 'desc';
  limit: number;
}

/** One bar per numeric field, each showing `stat` of that field across the layer. */
export interface FieldsBarChartConfig {
  mode: 'by_fields';
  fields: string[];
  stat: Statistic;
}

export type BarChartConfig =
  | CategoryBarChartConfig
  | DateBarChartConfig
  | FeatureBarChartConfig
  | FieldsBarChartConfig;

const KEYS = [
  'mode',
  'column',
  'stat',
  'stat_column',
  'limit',
  'label_column',
  'value_column',
  'sort',
  'fields',
  'date_bucket',
  'use_layer_colors',
] as const;

const MODES = ['category', 'date', 'by_feature', 'by_fields'] as const;

const absent = (value: unknown) => value === undefined || value === null;

/** Whether a column-valued key is set to a valid name, or is absent where it must be. */
function columnOrAbsent(value: unknown, required: boolean): boolean {
  return required ? isColumnName(value) : absent(value);
}

/** The server's rules for `BarChartConfig`: each mode needs its keys and refuses the others'. */
function parseBarChartConfig(config: unknown): BarChartConfig | null {
  if (!configKeys(config, KEYS)) return null;
  const raw = config as Record<string, unknown>;
  const { mode = 'category', stat = 'count', limit = 10, sort = 'desc', fields = [] } = raw;
  if (!MODES.includes(mode as (typeof MODES)[number])) return null;
  if (!isStatistic(stat)) return null;
  if (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > MAX_BARS) return null;
  if (sort !== 'asc' && sort !== 'desc') return null;
  if (!Array.isArray(fields) || !fields.every(isColumnName) || fields.length > MAX_FIELDS) return null;
  if (new Set(fields).size !== fields.length) return null;
  const { column, stat_column, label_column, value_column, date_bucket, use_layer_colors } = raw;
  if (use_layer_colors !== undefined && typeof use_layer_colors !== 'boolean') return null;
  if (date_bucket !== undefined && date_bucket !== null && !DATE_BUCKETS.includes(date_bucket as DateBucket)) {
    return null;
  }

  const grouped = mode === 'category' || mode === 'date';
  if (!columnOrAbsent(column, grouped)) return null;
  if (!columnOrAbsent(label_column, mode === 'by_feature') || !columnOrAbsent(value_column, mode === 'by_feature')) {
    return null;
  }
  if (grouped ? stat === 'count' ? !absent(stat_column) : !isColumnName(stat_column) : !absent(stat_column)) {
    return null;
  }
  if (!columnOrAbsent(date_bucket, mode === 'date')) return null;
  if ((fields.length > 0) !== (mode === 'by_fields')) return null;
  if (sort !== 'desc' && mode !== 'by_feature') return null;
  if (use_layer_colors === false && mode !== 'category') return null;

  switch (mode) {
    case 'category':
      return {
        column: column as string,
        stat,
        stat_column: (stat_column ?? null) as string | null,
        limit: limit as number,
        ...(use_layer_colors === false ? { use_layer_colors } : {}),
      };
    case 'date':
      return {
        mode,
        column: column as string,
        date_bucket: date_bucket as DateBucket,
        stat,
        stat_column: (stat_column ?? null) as string | null,
        limit: limit as number,
      };
    case 'by_feature':
      return {
        mode,
        label_column: label_column as string,
        value_column: value_column as string,
        sort,
        limit: limit as number,
      };
    default:
      return { mode: 'by_fields', fields: fields as string[], stat };
  }
}

/** Whether a stored config uses an option version 1 can't hold. */
export function needsVersion2(config: BarChartConfig): boolean {
  if (config.mode !== undefined && config.mode !== 'category') return true;
  return config.use_layer_colors === false;
}

/** The column a reader's pick on this chart filters, if its bars stand for values of one. */
export function pickedColumn(config: BarChartConfig): string | null {
  switch (config.mode) {
    case 'by_feature':
      return config.label_column;
    case 'by_fields':
    case 'date':
      return null;
    default:
      return config.column;
  }
}

/** The column whose layer colours the bars take, when the author hasn't turned them off. */
export function layerColorColumn(config: BarChartConfig): string | null {
  if (config.mode !== undefined && config.mode !== 'category') return null;
  return config.use_layer_colors === false ? null : config.column;
}

/** The statistic request shared by the category and date forms. */
function groupStat(config: CategoryBarChartConfig | DateBarChartConfig) {
  return config.stat === 'count' || config.stat_column === null
    ? { stat: 'count' as const }
    : { stat: aggregateStat(config.stat), column: config.stat_column };
}

export const barChartWidget = defineWidget<BarChartConfig>({
  type: 'bar_chart',
  v: 2,
  storedVersion: (config) => (needsVersion2(config) ? 2 : 1),
  surfaces: ['dashboard'],
  labelKey: 'types.bar_chart.label',
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
    'editor.statNames.count',
    'editor.statNames.sum',
    'editor.statNames.mean',
    'editor.statNames.min',
    'editor.statNames.max',
    'types.bar_chart.summary',
    'types.bar_chart.summaryDate',
    'types.bar_chart.summaryFeature',
    'types.bar_chart.summaryFields',
    'types.bar_chart.fieldHeader',
    'types.bar_chart.buckets.day',
    'types.bar_chart.buckets.week',
    'types.bar_chart.buckets.month',
    'types.bar_chart.buckets.year',
    'types.bar_chart.moreBuckets',
    'types.bar_chart.moreFeatures',
    'types.bar_chart.roleDescription',
    'types.bar_chart.keyboardHint',
    'types.bar_chart.keyboardHintPick',
    'types.bar_chart.keyboardHintPickPage',
    'types.bar_chart.bar',
  ],
  // `name` is a placeholder: a chart added in the Builder takes its column from
  // initialConfig, and the Builder holds a save naming a column the layer lacks.
  defaultConfig: { column: 'name', stat: 'count', stat_column: null, limit: 10 },
  initialConfig: categoryColumn,
  parseConfig: parseBarChartConfig,
  heading: (config, t, columnLabel) => {
    switch (config.mode) {
      case 'by_feature':
        return t('types.bar_chart.summaryFeature', {
          value: columnLabel(config.value_column),
          label: columnLabel(config.label_column),
        });
      case 'by_fields':
        return t('types.bar_chart.summaryFields', { stat: t(`editor.statNames.${config.stat}`) });
      case 'date':
        return t('types.bar_chart.summaryDate', {
          stat: t(STAT_LABEL_KEYS[config.stat], { column: config.stat_column && columnLabel(config.stat_column) }),
          bucket: t(`types.bar_chart.buckets.${config.date_bucket}`),
        });
      default:
        return t('types.bar_chart.summary', {
          stat: t(STAT_LABEL_KEYS[config.stat], { column: config.stat_column && columnLabel(config.stat_column) }),
          column: columnLabel(config.column),
        });
    }
  },
  dataRequest: (config) => {
    switch (config.mode) {
      case 'by_feature':
        return {
          op: 'rows',
          columns: [config.label_column, config.value_column],
          sort_column: config.value_column,
          sort: config.sort,
          limit: config.limit,
        };
      case 'by_fields':
        return { op: 'stats_by_fields', columns: config.fields, stats: [aggregateStat(config.stat)] };
      case 'date':
        return {
          op: 'group_by',
          group_column: config.column,
          date_bucket: config.date_bucket,
          ...groupStat(config),
          limit: config.limit,
        };
      default:
        return config.stat === 'count' || config.stat_column === null
          ? { op: 'value_counts', column: config.column, limit: config.limit }
          : { op: 'group_by', group_column: config.column, ...groupStat(config), limit: config.limit };
    }
  },
  // Bars that aren't values of one column name none, so the host passes no onSelect.
  picksColumn: (config) => pickedColumn(config) ?? '',
  readsColumns: (config) => {
    switch (config.mode) {
      case 'by_feature':
        return [
          { name: config.label_column, numeric: false },
          { name: config.value_column, numeric: true, sortable: true },
        ];
      case 'by_fields':
        return config.fields.map((name) => ({ name, numeric: true }));
      default:
        return [
          { name: config.column, numeric: false, ...(config.mode === 'date' ? { date: true } : {}) },
          ...(config.stat === 'count' || config.stat_column === null
            ? []
            : [{ name: config.stat_column, numeric: true }]),
        ];
    }
  },
  loadRenderer: () => import('./BarChartRenderer'),
  loadEditor: () => import('./BarChartEditor'),
  Fallback: BarChartFallback,
});
