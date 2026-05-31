import { getPlugins } from './registry';
import type { PluginDefinition } from './types';

/**
 * Availability gating for plugins. A plugin id is "available" when it is both
 * registered AND present in the enabled set (or the enabled set is null = all).
 */
export function getEnabledPluginDefinitions(
  enabledPluginIds: string[] | null
): PluginDefinition[] {
  const all = getPlugins();
  if (enabledPluginIds === null) return all;
  const set = new Set(enabledPluginIds);
  return all.filter((w) => set.has(w.id));
}

/**
 * Check if a plugin id is available given the enabled set.
 */
export function isPluginIdAvailable(
  pluginId: string,
  enabledPluginIds: string[] | null
): boolean {
  if (enabledPluginIds === null) return true;
  return enabledPluginIds.includes(pluginId);
}

/**
 * Resolve the available plugin ids from the enabled set, falling back to all
 * registered plugin ids when the enabled set is null.
 */
export function resolveAvailablePluginIds(
  enabledPluginIds: string[] | null
): string[] {
  const all = getPlugins().map((w) => w.id);
  if (enabledPluginIds === null) return all;
  return all.filter((id) => enabledPluginIds.includes(id));
}

/**
 * Default plugin ids = all registered (used when no explicit enabled set).
 */
export function getDefaultPluginIds(): string[] {
  return getPlugins().map((w) => w.id);
}

/**
 * Compare two plugin id arrays for set-equality (order-insensitive).
 */
export function samePluginIds(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = new Set(a);
  return b.every((id) => sa.has(id));
}
