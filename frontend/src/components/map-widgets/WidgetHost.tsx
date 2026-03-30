import { useMemo } from 'react';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import { WidgetErrorBoundary } from './WidgetErrorBoundary';
import type { WidgetContext, WidgetAnchor, WidgetDefinition } from './types';

const ANCHOR_POSITIONS: Record<WidgetAnchor, string> = {
  'top-left': 'absolute top-3 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-14 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-20 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};

/** Shared hook: partition active+enabled widgets by placement mode */
export function usePartitionedWidgets() {
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const { data: enabledWidgetIds } = useEnabledWidgets();

  return useMemo(() => {
    const allRegistered = getWidgets();
    const enabledSet = enabledWidgetIds == null ? null : new Set(enabledWidgetIds);

    const definitions = allRegistered.filter(
      (w) => activeWidgets.has(w.id) && (enabledSet === null || enabledSet.has(w.id)),
    );

    const byAnchor: Record<string, WidgetDefinition[]> = {};
    const sidebar: WidgetDefinition[] = [];

    for (const w of definitions) {
      if (w.placement.mode === 'floating') {
        const anchor = w.placement.anchor;
        (byAnchor[anchor] ??= []).push(w);
      } else {
        sidebar.push(w);
      }
    }

    return { byAnchor, sidebar };
  }, [activeWidgets, enabledWidgetIds]);
}

interface WidgetHostProps {
  ctx: WidgetContext;
}

/** Renders floating widgets anchored to map corners */
export function WidgetHost({ ctx }: WidgetHostProps) {
  const { byAnchor } = usePartitionedWidgets();
  const anchors = Object.keys(ANCHOR_POSITIONS) as WidgetAnchor[];

  return (
    <>
      {anchors.map((anchor) => {
        const widgets = byAnchor[anchor] ?? [];
        if (widgets.length === 0) return null;
        const className = ANCHOR_POSITIONS[anchor];
        return (
          <div key={anchor} className={className}>
            {widgets.map((w) => (
              <WidgetPanel key={w.id} def={w}>
                <WidgetErrorBoundary widgetId={w.id}>
                  <w.component ctx={ctx} />
                </WidgetErrorBoundary>
              </WidgetPanel>
            ))}
          </div>
        );
      })}
    </>
  );
}

interface WidgetSidebarSectionProps {
  ctx: WidgetContext;
}

/** Renders sidebar-mode widgets as sections inside the existing builder sidebar */
export function WidgetSidebarSection({ ctx }: WidgetSidebarSectionProps) {
  const { sidebar } = usePartitionedWidgets();

  if (sidebar.length === 0) return null;

  return (
    <>
      {sidebar.map((w) => (
        <div key={w.id} className="border-t pt-3 px-2">
          <WidgetPanel def={w}>
            <WidgetErrorBoundary widgetId={w.id}>
              <w.component ctx={ctx} />
            </WidgetErrorBoundary>
          </WidgetPanel>
        </div>
      ))}
    </>
  );
}
