import { LayoutGrid } from 'lucide-react';
import { registerPlugin, getPlugins, getPlugin } from '../registry';

// The registry is module-level state. Tests share it with the side-effect
// registration in register-plugins.ts (imported via index.ts barrel).
// We test additive behavior rather than assuming an empty registry.

describe('plugin registry', () => {
  const testPlugin = {
    id: 'test-plugin-registry-spec',
    labelKey: 'Test Plugin',
    icon: LayoutGrid,
    placement: { mode: 'floating' as const, anchor: 'top-right' as const },
    component: () => null,
  };

  it('registerPlugin adds a plugin to the registry', () => {
    const before = getPlugins().length;
    registerPlugin(testPlugin);
    expect(getPlugins().length).toBe(before + 1);
  });

  it('getPlugin returns a registered plugin by ID', () => {
    const found = getPlugin(testPlugin.id);
    expect(found).toBeDefined();
    expect(found?.labelKey).toBe('Test Plugin');
  });

  it('getPlugin returns undefined for unknown ID', () => {
    expect(getPlugin('nonexistent-plugin')).toBeUndefined();
  });

  it('getPlugins returns all registered plugins', () => {
    const all = getPlugins();
    expect(all.length).toBeGreaterThanOrEqual(1);
    expect(all.some((w) => w.id === testPlugin.id)).toBe(true);
  });

  it('duplicate registration warns and overwrites', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const updated = { ...testPlugin, labelKey: 'Updated Plugin' };
    registerPlugin(updated);

    expect(spy).toHaveBeenCalledWith(expect.stringContaining(testPlugin.id));
    expect(getPlugin(testPlugin.id)?.labelKey).toBe('Updated Plugin');
    spy.mockRestore();
  });
});
