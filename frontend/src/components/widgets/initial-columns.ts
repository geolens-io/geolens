import { isAggregateNumeric, isTextColumn } from '@/lib/column-utils';
import type { WidgetColumn } from './contract';

// A unique identifier gives every row its own category, so a new widget avoids one when it can.
const IDENTIFIER = /^(id|gid|fid|uuid|globalid|objectid)$|_id$/i;
// The most distinct values the ingest samples per column (get_sample_values).
const SAMPLE_LIMIT = 10;

/**
 * The column a new chart or selector groups by: the first text column that
 * isn't an identifier and whose sample holds two to nine values, so it has few
 * categories. Without such a sample, the first text column that isn't an
 * identifier, then any text column, then the first column.
 */
export function categoryColumn(columns: readonly WidgetColumn[]): { column?: string } {
  const text = columns.filter((column) => isTextColumn(column.type));
  const named = text.filter((column) => !IDENTIFIER.test(column.name));
  const few = named.find((column) => {
    const sampled = column.samples?.length ?? 0;
    return sampled >= 2 && sampled < SAMPLE_LIMIT;
  });
  const pick = few ?? named[0] ?? text[0] ?? columns[0];
  return pick ? { column: pick.name } : {};
}

/** The column a new histogram bins: the first numeric column that isn't an identifier, else the first numeric one. */
export function numericColumn(columns: readonly WidgetColumn[]): { column?: string } {
  const numeric = columns.filter((column) => isAggregateNumeric(column.type));
  const pick = numeric.find((column) => !IDENTIFIER.test(column.name)) ?? numeric[0];
  return pick ? { column: pick.name } : {};
}
