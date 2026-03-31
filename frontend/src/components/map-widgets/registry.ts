import type { WidgetDefinition } from './types';

const registry = new Map<string, WidgetDefinition>();
let cache: WidgetDefinition[] | null = null;

export function registerWidget(def: WidgetDefinition): void {
  if (registry.has(def.id)) {
    if (import.meta.env.DEV) console.warn(`Widget "${def.id}" already registered, overwriting.`);
  }
  registry.set(def.id, def);
  cache = null;
}

export function getWidgets(): WidgetDefinition[] {
  return (cache ??= Array.from(registry.values()));
}

export function getWidget(id: string): WidgetDefinition | undefined {
  return registry.get(id);
}
