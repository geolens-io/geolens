import type { SelectionValue, WidgetSelection } from './contract';

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

/** Whether the pick holds exactly `keys`, so picking the same mark again clears it. */
export function picksExactly(picked: readonly SelectionValue[], keys: readonly SelectionValue[]): boolean {
  return picked.length === keys.length && keys.every((key) => picked.includes(key));
}
