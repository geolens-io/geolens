import { describe, it, expect } from 'vitest';
import { usePartitionedPlugins } from '../PluginHost';
import type { PluginDefinition } from '../registry';

describe('usePartitionedPlugins', () => {
  it('partitions plugin defs', () => {
    const defs: PluginDefinition[] = [];
    const active = new Set<string>();
    const result = usePartitionedPlugins(defs, active);
    expect(result).toBeDefined();
  });
});
