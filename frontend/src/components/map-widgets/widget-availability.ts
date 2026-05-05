import { getWidgets } from './registry';
import type { WidgetDefinition } from './types';

function enabledIdSet(enabledWidgetIds: string[] | null | undefined): Set<string> | null {
  return enabledWidgetIds == null ? null : new Set(enabledWidgetIds);
}

export function getEnabledWidgetDefinitions(
  enabledWidgetIds: string[] | null | undefined,
): WidgetDefinition[] {
  const enabledSet = enabledIdSet(enabledWidgetIds);
  return getWidgets().filter((widget) => enabledSet === null || enabledSet.has(widget.id));
}

export function isWidgetIdAvailable(
  id: string,
  enabledWidgetIds: string[] | null | undefined,
): boolean {
  return getEnabledWidgetDefinitions(enabledWidgetIds).some((widget) => widget.id === id);
}

export function resolveAvailableWidgetIds(
  widgetIds: Iterable<string>,
  enabledWidgetIds: string[] | null | undefined,
): string[] {
  const available = new Set(getEnabledWidgetDefinitions(enabledWidgetIds).map((widget) => widget.id));
  const resolved: string[] = [];
  const seen = new Set<string>();
  for (const id of widgetIds) {
    if (!available.has(id) || seen.has(id)) continue;
    resolved.push(id);
    seen.add(id);
  }
  return resolved;
}

export function getDefaultWidgetIds(enabledWidgetIds: string[] | null | undefined): string[] {
  return getEnabledWidgetDefinitions(enabledWidgetIds)
    .filter((widget) => widget.defaultVisible)
    .map((widget) => widget.id);
}

export function sameWidgetIds(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((id, index) => id === b[index]);
}
