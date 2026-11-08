import type { SelectionValue, WidgetSelection } from './contract';
import { isBlankValue } from './value-counts';

/** The values `selection` picks on `column`; none when it picks a range or another column. */
export function selectedValues(
  selection: WidgetSelection | null | undefined,
  column: string,
): readonly SelectionValue[] {
  return selection && selection.column === column && 'values' in selection ? selection.values : [];
}

/** Picking a mark that is already picked clears the pick. */
export function togglePick(alreadyPicked: boolean, pick: WidgetSelection): WidgetSelection | null {
  return alreadyPicked ? null : pick;
}

/**
 * Whether the pick is this row's own, so picking the row again clears it. The
 * merged no-value row owns a pick of any blank spelling; every other row needs
 * exactly its stored values.
 */
export function picksRow(
  picked: readonly SelectionValue[],
  row: { keys: readonly SelectionValue[]; blankCategory?: true },
): boolean {
  if (row.blankCategory) return picked.length > 0 && picked.every(isBlankValue);
  return picked.length === row.keys.length && row.keys.every((key) => picked.includes(key));
}
