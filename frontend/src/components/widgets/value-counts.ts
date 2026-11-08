import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { aggregateResult, formatAggregateValue } from './aggregate';
import type { SelectionValue, ValueLabel } from './contract';

export interface CategoryRow {
  /** The category as the endpoint sent it, which a pick filters on. */
  key: SelectionValue;
  label: string;
  /** The label with the stored value after it, as tables show a labelled value; undefined when the label stands alone. */
  tableLabel?: string;
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

/** Whether a stored value reads as nothing: null, or text that is empty or only spaces. */
export function isBlankValue(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
}

/** Looks up the layer's label for a stored value of one column. */
export type LabelOf = (value: unknown) => string | undefined;

/** The lookup for one column, or undefined where the host has no value labels. */
export function labelOfColumn(valueLabel: ValueLabel | undefined, column: string): LabelOf | undefined {
  return valueLabel && ((value) => valueLabel(column, value));
}

/** A category as readers see it: its label where the layer has one. A numeric one, such as a year or a code, otherwise reads best as stored. */
export function categoryLabel(key: SelectionValue, t: TFunction<'widgets'>, labelOf?: LabelOf): string {
  return isBlankValue(key) ? t('noValue') : (labelOf?.(key) ?? String(key));
}

/** A category for a table: "Label (code)" where the layer has a label, else as `categoryLabel`. */
export function categoryTableLabel(key: SelectionValue, t: TFunction<'widgets'>, labelOf?: LabelOf): string {
  const label = categoryLabel(key, t, labelOf);
  return isBlankValue(key) || label === String(key) ? label : `${label} (${String(key)})`;
}

/** The categories of a `value_counts` or `group_by` result, labelled in the reader's locale. */
export function useCategoryRows(data: unknown, labelOf?: LabelOf): CategoryRows {
  const { t } = useTranslation('widgets');
  const row = (key: SelectionValue, value: number | string | null): CategoryRow => ({
    key,
    label: categoryLabel(key, t, labelOf),
    tableLabel: categoryTableLabel(key, t, labelOf),
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
