import { useTranslation } from 'react-i18next';
import type { Bbox } from '@/lib/bbox';
import { aggregateResult, formatAggregateValue } from '../aggregate';
import type { FeatureListConfig } from './definition';

export interface FeatureRow {
  /** The feature's id, which the map identifies it by. */
  id: number | string;
  title: string;
  subtitle?: string;
  /** Null for a feature with no shape, or a layer with no geometry. */
  bbox: Bbox | null;
}

export interface FeatureRows {
  /** Undefined before the host has fetched the data. */
  rows?: FeatureRow[];
  hasMore: boolean;
}

function toBbox(value: readonly number[] | null | undefined): Bbox | null {
  return value && value.length === 4 && value.every(Number.isFinite) ? (value as Bbox) : null;
}

/** The features of a `rows` result, with their title and subtitle text in the reader's locale. */
export function useFeatureRows(config: FeatureListConfig, data: unknown): FeatureRows {
  const { t } = useTranslation('widgets');
  const result = aggregateResult(data, 'rows');
  if (!result) return { hasMore: false };
  const text = (value: unknown): string =>
    value === null || value === undefined
      ? String(t('noValue'))
      : typeof value === 'number'
        ? formatAggregateValue(value)
        : String(value);
  return {
    hasMore: result.has_more,
    rows: result.rows.map((row) => ({
      id: row.gid,
      title: text(row.values[config.title_column]),
      ...(config.subtitle_column === null ? {} : { subtitle: text(row.values[config.subtitle_column]) }),
      bbox: toBbox(row.bbox),
    })),
  };
}
