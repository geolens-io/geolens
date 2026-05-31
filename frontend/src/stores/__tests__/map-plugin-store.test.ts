import { usePluginStore } from '@/stores/map-plugin-store';

const initialState = usePluginStore.getState();

describe('usePluginStore', () => {
  beforeEach(() => {
    usePluginStore.setState(initialState, true);
  });

  it('starts with empty active plugins', () => {
    expect(usePluginStore.getState().activePlugins.size).toBe(0);
  });

  it('open adds a plugin', () => {
    usePluginStore.getState().open('test-plugin');
    expect(usePluginStore.getState().activePlugins.has('test-plugin')).toBe(true);
  });

  it('open is idempotent', () => {
    usePluginStore.getState().open('test-plugin');
    usePluginStore.getState().open('test-plugin');
    expect(usePluginStore.getState().activePlugins.size).toBe(1);
  });

  it('close removes a plugin', () => {
    usePluginStore.getState().open('test-plugin');
    usePluginStore.getState().close('test-plugin');
    expect(usePluginStore.getState().activePlugins.has('test-plugin')).toBe(false);
  });

  it('close on non-existent plugin is a no-op', () => {
    usePluginStore.getState().close('nonexistent');
    expect(usePluginStore.getState().activePlugins.size).toBe(0);
  });

  it('toggle opens a closed plugin', () => {
    usePluginStore.getState().toggle('test-plugin');
    expect(usePluginStore.getState().activePlugins.has('test-plugin')).toBe(true);
  });

  it('toggle closes an open plugin', () => {
    usePluginStore.getState().open('test-plugin');
    usePluginStore.getState().toggle('test-plugin');
    expect(usePluginStore.getState().activePlugins.has('test-plugin')).toBe(false);
  });

  it('manages multiple plugins independently', () => {
    const { open, close } = usePluginStore.getState();
    open('a');
    open('b');
    open('c');
    close('b');

    const { activePlugins } = usePluginStore.getState();
    expect(activePlugins.has('a')).toBe(true);
    expect(activePlugins.has('b')).toBe(false);
    expect(activePlugins.has('c')).toBe(true);
    expect(activePlugins.size).toBe(2);
  });

  it('replace sets the active plugin list deterministically', () => {
    usePluginStore.getState().open('old-plugin');
    usePluginStore.getState().replace(['legend', 'measurement']);

    const { activePlugins } = usePluginStore.getState();
    expect(Array.from(activePlugins)).toEqual(['legend', 'measurement']);
  });
});
