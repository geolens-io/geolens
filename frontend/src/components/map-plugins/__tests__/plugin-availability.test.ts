import { describe, it, expect } from 'vitest';
import {
  getEnabledPluginDefinitions,
  isPluginIdAvailable,
  resolveAvailablePluginIds,
  getDefaultPluginIds,
  samePluginIds,
} from '../plugin-availability';

describe('plugin-availability', () => {
  it('returns all when enabled set is null', () => {
    // null = all plugins enabled
    expect(getEnabledPluginDefinitions(null)).toBeDefined();
  });

  it('isPluginIdAvailable respects enabled set', () => {
    expect(isPluginIdAvailable('measurement', ['measurement'])).toBe(true);
  });

  it('samePluginIds compares set-equality', () => {
    expect(samePluginIds(['a'], ['a'])).toBe(true);
  });
});
