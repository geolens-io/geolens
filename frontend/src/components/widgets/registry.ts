import type { WidgetDefinition } from './types';

const registry = new Map<string, WidgetDefinition>();

export function registerWidget(def: WidgetDefinition): void {
  if (registry.has(def.id)) {
    console.warn(`Widget "${def.id}" already registered, overwriting.`);
  }
  registry.set(def.id, def);
}

export function getWidgets(): WidgetDefinition[] {
  return Array.from(registry.values());
}

export function getWidget(id: string): WidgetDefinition | undefined {
  return registry.get(id);
}
