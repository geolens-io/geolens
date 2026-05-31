import { describe, it, expect } from 'vitest';
import { usePluginStore } from '@/stores/map-plugin-store';

describe('store-relocation-smoke', () => {
  it('store is importable at the plugin path', () => {
    // verifies @/stores/map-plugin-store resolves post-rename
    usePluginStore.getState().open('measurement');
    expect(usePluginStore.getState().isOpen('measurement')).toBe(true);
  });
});
