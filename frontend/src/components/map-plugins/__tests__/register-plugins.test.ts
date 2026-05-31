import '../register-plugins';
import { getPlugin } from '../registry';

// Pins the built-in registration set so an accidental anchor / defaultVisible /
// labelKey flip during a refactor (e.g. the Widget→Plugin rename) is caught.
// register-plugins.ts is the source of truth; these assertions mirror it.
describe('built-in plugin registration', () => {
  it('registers the measurement plugin: floating top-left, not default-visible', () => {
    const def = getPlugin('measurement');
    expect(def).toBeDefined();
    expect(def?.labelKey).toBe('plugins.measurement.label');
    expect(def?.defaultVisible).toBe(false);
    expect(def?.placement.mode).toBe('floating');
    if (def?.placement.mode === 'floating') {
      expect(def.placement.anchor).toBe('top-left');
    }
  });

  it('registers the legend plugin: floating bottom-left, default-visible', () => {
    const def = getPlugin('legend');
    expect(def).toBeDefined();
    expect(def?.labelKey).toBe('plugins.legend.label');
    expect(def?.defaultVisible).toBe(true);
    expect(def?.placement.mode).toBe('floating');
    if (def?.placement.mode === 'floating') {
      expect(def.placement.anchor).toBe('bottom-left');
    }
  });

  it('uses stable lowercase-slug IDs suitable for saved-map JSON', () => {
    for (const id of ['measurement', 'legend']) {
      expect(getPlugin(id)?.id).toBe(id);
      expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
    }
  });
});
