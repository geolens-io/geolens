import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { aggregateResult, formatAggregateValue } from './aggregate';
import type { SelectionValue } from './contract';

interface CategoryRow {
  /** The category as the endpoint sent it, which a pick filters on. */
  key: SelectionValue;
  label: string;
  /** The exact value as text, for tables and readouts. */
  text: string;
  /** The value as a number for drawing; NaN when it has none. */
  amount: number;
}

export interface CategoryRows {
  /** Undefined before the host has fetched the data. */
  rows?: CategoryRow[];
  /** Rows a top-N count leaves out, as text; undefined when there are none. */
  other?: string;
}

/** A category as readers see it. A numeric one, such as a year or a code, reads best as stored. */
export function categoryLabel(key: SelectionValue, t: TFunction<'widgets'>): string {
  return key === null ? t('noValue') : String(key);
}

/** The categories of a `value_counts` or `group_by` result, labelled in the reader's locale. */
export function useCategoryRows(data: unknown): CategoryRows {
  const { t } = useTranslation('widgets');
  const row = (key: SelectionValue, value: number | string | null): CategoryRow => ({
    key,
    label: categoryLabel(key, t),
    text: formatAggregateValue(value),
    amount: value === null ? Number.NaN : Number(value),
  });
  const counts = aggregateResult(data, 'value_counts');
  if (counts) {
    return {
      rows: counts.values.map((entry) => row(entry.value ?? null, entry.count)),
      other: counts.other_count > 0 ? formatAggregateValue(counts.other_count) : undefined,
    };
  }
  const groups = aggregateResult(data, 'group_by');
  if (groups) return { rows: groups.groups.map((group) => row(group.key ?? null, group.value ?? null)) };
  return {};
}
