import { useTranslation } from 'react-i18next';
import type { Bbox } from '@/lib/bbox';
import { formatNumber } from '@/lib/format';
import { aggregateResult } from '../aggregate';
import type { ValueLabel } from '../contract';
import { isBlankValue, labelOfColumn, type LabelOf } from '../value-counts';
import type { FeatureListConfig } from './definition';

export interface FeatureRow {
  /** The feature's id, which the map identifies it by. */
  id: number | string;
  title: string;
  subtitle?: string;
  /** The title and subtitle with the stored value after a label, for the text alternative. */
  listTitle: string;
  listSubtitle?: string;
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
export function useFeatureRows(config: FeatureListConfig, data: unknown, valueLabel?: ValueLabel): FeatureRows {
  const { t } = useTranslation('widgets');
  const result = aggregateResult(data, 'rows');
  if (!result) return { hasMore: false };
  const text = (value: unknown, labelOf?: LabelOf): string =>
    isBlankValue(value)
      ? String(t('noValue'))
      : (labelOf?.(value) ??
        (typeof value === 'number' ? formatNumber(value, { maximumFractionDigits: 2 }) : String(value)));
  const withCode = (value: unknown, labelOf?: LabelOf): string => {
    const label = text(value, labelOf);
    return labelOf?.(value) === undefined ? label : `${label} (${String(value)})`;
  };
  const titleOf = labelOfColumn(valueLabel, config.title_column);
  const subtitleOf = config.subtitle_column === null ? undefined : labelOfColumn(valueLabel, config.subtitle_column);
  return {
    hasMore: result.has_more,
    rows: result.rows.map((row) => {
      const subtitle = config.subtitle_column === null ? undefined : row.values[config.subtitle_column];
      return {
        id: row.gid,
        title: text(row.values[config.title_column], titleOf),
        listTitle: withCode(row.values[config.title_column], titleOf),
        ...(config.subtitle_column === null
          ? {}
          : { subtitle: text(subtitle, subtitleOf), listSubtitle: withCode(subtitle, subtitleOf) }),
        bbox: toBbox(row.bbox),
      };
    }),
  };
}
