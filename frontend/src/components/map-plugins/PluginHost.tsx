import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { usePluginStore } from '@/stores/map-plugin-store';
import { getEnabledPluginDefinitions } from './plugin-availability';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { PluginErrorBoundary } from './PluginErrorBoundary';
import type { PluginContext, PluginDefinition } from './types';
import { PluginPanel } from './PluginPanel';

export function PluginHost({
  mapId,
  enabledPluginIds,
  context,
}: {
  mapId: string;
  enabledPluginIds: string[] | null;
  context: PluginContext;
}) {
  const { t } = useTranslation('builder');
  const activePlugins = usePluginStore((s) => s.activePlugins);
  const enabledDefs = useMemo(
    () => getEnabledPluginDefinitions(enabledPluginIds),
    [enabledPluginIds]
  );
  const partitioned = usePartitionedPlugins(enabledDefs, activePlugins);
  return (
    <PluginErrorBoundary t={t}>
      <PluginPanel
        mapId={mapId}
        plugins={partitioned}
        context={context}
      />
    </PluginErrorBoundary>
  );
}

export function usePartitionedPlugins(defs: PluginDefinition[], active: Set<string>) {
  return useMemo(() => ({ defs, active }), [defs, active]);
}
