import { describe, it, expect, beforeEach } from 'vitest';
import { usePluginStore } from '../map-plugin-store';

describe('map-plugin-store', () => {
  beforeEach(() => {
    usePluginStore.setState({ activePlugins: new Set<string>() });
  });

  it('opens a plugin id', () => {
    usePluginStore.getState().open('measurement');
    expect(usePluginStore.getState().isOpen('measurement')).toBe(true);
  });

  it('closes a plugin id', () => {
    usePluginStore.getState().open('legend');
    usePluginStore.getState().close('legend');
    expect(usePluginStore.getState().isOpen('legend')).toBe(false);
  });

  it('toggles a plugin id', () => {
    usePluginStore.getState().toggle('measurement');
    expect(usePluginStore.getState().isOpen('measurement')).toBe(true);
  });
});
