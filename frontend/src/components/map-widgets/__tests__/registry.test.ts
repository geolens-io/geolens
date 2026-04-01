import { LayoutGrid } from 'lucide-react';
import { registerWidget, getWidgets, getWidget } from '../registry';

// The registry is module-level state. Tests share it with the side-effect
// registration in register-widgets.ts (imported via index.ts barrel).
// We test additive behavior rather than assuming an empty registry.

describe('widget registry', () => {
  const testWidget = {
    id: 'test-widget-registry-spec',
    labelKey: 'Test Widget',
    icon: LayoutGrid,
    placement: { mode: 'floating' as const, anchor: 'top-right' as const },
    component: () => null,
  };

  it('registerWidget adds a widget to the registry', () => {
    const before = getWidgets().length;
    registerWidget(testWidget);
    expect(getWidgets().length).toBe(before + 1);
  });

  it('getWidget returns a registered widget by ID', () => {
    const found = getWidget(testWidget.id);
    expect(found).toBeDefined();
    expect(found?.labelKey).toBe('Test Widget');
  });

  it('getWidget returns undefined for unknown ID', () => {
    expect(getWidget('nonexistent-widget')).toBeUndefined();
  });

  it('getWidgets returns all registered widgets', () => {
    const all = getWidgets();
    expect(all.length).toBeGreaterThanOrEqual(1);
    expect(all.some((w) => w.id === testWidget.id)).toBe(true);
  });

  it('duplicate registration warns and overwrites', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const updated = { ...testWidget, labelKey: 'Updated Widget' };
    registerWidget(updated);

    expect(spy).toHaveBeenCalledWith(expect.stringContaining(testWidget.id));
    expect(getWidget(testWidget.id)?.labelKey).toBe('Updated Widget');
    spy.mockRestore();
  });
});
