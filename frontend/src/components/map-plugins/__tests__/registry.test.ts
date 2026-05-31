import { describe, it, expect, beforeEach } from 'vitest';
import { registerPlugin, getPlugins, getPlugin } from '../registry';
import type { PluginDefinition } from '../registry';

describe('plugin registry', () => {
  const def: PluginDefinition = {
    id: 'measurement',
    anchor: 'top-left',
    placement: 'panel',
    component: () => null,
  };

  beforeEach(() => {
    // registry is module-singleton; re-register for each test
    registerPlugin(def);
  });

  it('registers and retrieves a plugin by id', () => {
    registerPlugin(def);
    expect(getPlugin('measurement')).toBeDefined();
  });

  it('lists all registered plugins', () => {
    expect(getPlugins().length).toBeGreaterThan(0);
  });
});
