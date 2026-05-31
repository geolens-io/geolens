import type { PluginDefinition } from './types';

export type { PluginDefinition };

const registry = new Map<string, PluginDefinition>();

/**
 * Register a plugin definition. Idempotent by id (last registration wins).
 */
export function registerPlugin(def: PluginDefinition) {
  registry.set(def.id, def);
}

/**
 * Get all registered plugin definitions in registration order.
 */
export function getPlugins(): PluginDefinition[] {
  return Array.from(registry.values());
}

/**
 * Get a single plugin definition by id, or undefined.
 */
export function getPlugin(id: string): PluginDefinition | undefined {
  return registry.get(id);
}
