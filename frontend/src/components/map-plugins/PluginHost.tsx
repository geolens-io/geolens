import { useMemo } from 'react';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getPlugins } from './registry';
import { resolveAvailablePluginIds } from './plugin-availability';
import { PluginPanel } from './PluginPanel';
import { PluginErrorBoundary } from './PluginErrorBoundary';
import type { PluginContext, PluginAnchor, PluginDefinition } from './types';

// Anchor offsets account for map overlay controls:
// top-left: below MapToolbar (h-8 + top-3 = ~44px ≈ top-12)
// top-right: below MapToolbar row
// bottom-left: above ScaleControl (~24px) + EphemeralBadge (~32px)
// bottom-right: above NavigationControl
const ANCHOR_POSITIONS: Record<PluginAnchor, string> = {
  'top-left': 'absolute top-12 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-12 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-14 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};

const ANCHORS = Object.keys(ANCHOR_POSITIONS) as PluginAnchor[];

/** Partition active+enabled plugins by placement mode. Call once in the parent. */
export function usePartitionedPlugins() {
  const activePlugins = usePluginStore((s) => s.activePlugins);
  const enabledPluginsQuery = useEnabledWidgets();
  const enabledPluginIds = useMemo(
    () => enabledPluginsQuery.data ?? (enabledPluginsQuery.isLoading ? [] : null),
    [enabledPluginsQuery.data, enabledPluginsQuery.isLoading],
  );

  return useMemo(() => {
    const allRegistered = getPlugins();
    const activeEnabledIds = new Set(resolveAvailablePluginIds(activePlugins, enabledPluginIds));

    const definitions = allRegistered.filter(
      (w) => activeEnabledIds.has(w.id),
    );

    const byAnchor: Partial<Record<PluginAnchor, PluginDefinition[]>> = {};
    const sidebar: PluginDefinition[] = [];

    for (const w of definitions) {
      if (w.placement.mode === 'floating') {
        const anchor = w.placement.anchor;
        (byAnchor[anchor] ??= []).push(w);
      } else if (w.placement.mode === 'sidebar') {
        sidebar.push(w);
      }
    }

    return { byAnchor, sidebar };
  }, [activePlugins, enabledPluginIds]);
}

interface PluginHostProps {
  byAnchor: Partial<Record<PluginAnchor, PluginDefinition[]>>;
  ctx: PluginContext;
  /** Extra content rendered inside the top-left anchor (e.g., filter chips). */
  topLeftSlot?: React.ReactNode;
}

/** Renders floating plugins anchored to map corners */
export function PluginHost({ byAnchor, ctx, topLeftSlot }: PluginHostProps) {
  return (
    <>
      {ANCHORS.map((anchor) => {
        const plugins = byAnchor[anchor] ?? [];
        const slot = anchor === 'top-left' ? topLeftSlot : null;
        if (plugins.length === 0 && !slot) return null;
        const className = ANCHOR_POSITIONS[anchor];
        return (
          <div key={anchor} className={className}>
            {plugins.map((w) => (
              <PluginPanel key={w.id} def={w}>
                <PluginErrorBoundary pluginId={w.id}>
                  <w.component ctx={ctx} />
                </PluginErrorBoundary>
              </PluginPanel>
            ))}
            {slot}
          </div>
        );
      })}
    </>
  );
}

interface PluginSidebarProps {
  plugins: PluginDefinition[];
  ctx: PluginContext;
}

/** Renders sidebar-placement plugins in the builder sidebar. */
export function PluginSidebar({ plugins, ctx }: PluginSidebarProps) {
  if (plugins.length === 0) return null;

  return (
    <div className="px-2 space-y-2">
      {plugins.map((w) => (
        <PluginPanel key={w.id} def={w}>
          <PluginErrorBoundary pluginId={w.id}>
            <w.component ctx={ctx} />
          </PluginErrorBoundary>
        </PluginPanel>
      ))}
    </div>
  );
}
