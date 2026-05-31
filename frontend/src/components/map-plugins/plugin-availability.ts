import { getPlugins } from './registry';
import type { PluginDefinition } from './types';

function enabledIdSet(enabledPluginIds: string[] | null | undefined): Set<string> | null {
  return enabledPluginIds == null ? null : new Set(enabledPluginIds);
}

export function getEnabledPluginDefinitions(
  enabledPluginIds: string[] | null | undefined,
): PluginDefinition[] {
  const enabledSet = enabledIdSet(enabledPluginIds);
  return getPlugins().filter((plugin) => enabledSet === null || enabledSet.has(plugin.id));
}

export function isPluginIdAvailable(
  id: string,
  enabledPluginIds: string[] | null | undefined,
): boolean {
  return getEnabledPluginDefinitions(enabledPluginIds).some((plugin) => plugin.id === id);
}

export function resolveAvailablePluginIds(
  pluginIds: Iterable<string>,
  enabledPluginIds: string[] | null | undefined,
): string[] {
  const available = new Set(getEnabledPluginDefinitions(enabledPluginIds).map((plugin) => plugin.id));
  const resolved: string[] = [];
  const seen = new Set<string>();
  for (const id of pluginIds) {
    if (!available.has(id) || seen.has(id)) continue;
    resolved.push(id);
    seen.add(id);
  }
  return resolved;
}

export function getDefaultPluginIds(enabledPluginIds: string[] | null | undefined): string[] {
  return getEnabledPluginDefinitions(enabledPluginIds)
    .filter((plugin) => plugin.defaultVisible)
    .map((plugin) => plugin.id);
}

export function samePluginIds(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((id, index) => id === b[index]);
}
