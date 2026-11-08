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
 * Whether the pick holds exactly `keys`, so picking the same mark again clears
 * it. Null and blank text are one category in any spelling.
 */
export function picksExactly(picked: readonly SelectionValue[], keys: readonly SelectionValue[]): boolean {
  const asCategory = (value: SelectionValue) => (isBlankValue(value) ? null : value);
  const pickedCategories = new Set(picked.map(asCategory));
  const keyCategories = new Set(keys.map(asCategory));
  return pickedCategories.size === keyCategories.size && [...keyCategories].every((key) => pickedCategories.has(key));
}
