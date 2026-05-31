import '../register-plugins';
import {
  getDefaultPluginIds,
  isPluginIdAvailable,
  resolveAvailablePluginIds,
  samePluginIds,
} from '../plugin-availability';

describe('plugin availability helpers', () => {
  it('treats null or undefined enabled plugins as no restriction', () => {
    expect(isPluginIdAvailable('legend', null)).toBe(true);
    expect(isPluginIdAvailable('measurement', undefined)).toBe(true);
  });

  it('filters unknown and admin-disabled IDs while preserving order', () => {
    expect(resolveAvailablePluginIds(['unknown', 'measurement', 'legend', 'measurement'], ['legend', 'measurement'])).toEqual([
      'measurement',
      'legend',
    ]);
    expect(resolveAvailablePluginIds(['measurement', 'legend'], ['legend'])).toEqual(['legend']);
  });

  it('resolves default visible plugins through admin enablement', () => {
    expect(getDefaultPluginIds(null)).toEqual(['legend']);
    expect(getDefaultPluginIds(['measurement'])).toEqual([]);
    expect(getDefaultPluginIds(['legend'])).toEqual(['legend']);
  });

  it('compares plugin ID arrays by exact saved order', () => {
    expect(samePluginIds(['legend', 'measurement'], ['legend', 'measurement'])).toBe(true);
    expect(samePluginIds(['measurement', 'legend'], ['legend', 'measurement'])).toBe(false);
  });
});
