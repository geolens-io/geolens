import type { PluginDefinition } from './types';

const registry = new Map<string, PluginDefinition>();
let cache: PluginDefinition[] | null = null;

export function registerPlugin(def: PluginDefinition): void {
  if (registry.has(def.id)) {
    if (import.meta.env.DEV) console.warn(`Plugin "${def.id}" already registered, overwriting.`);
  }
  registry.set(def.id, def);
  cache = null;
}

export function getPlugins(): PluginDefinition[] {
  return (cache ??= Array.from(registry.values()));
}

export function getPlugin(id: string): PluginDefinition | undefined {
  return registry.get(id);
}
