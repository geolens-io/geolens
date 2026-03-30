import { useMemo } from 'react';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import { WidgetSidebar } from './WidgetSidebar';
import { WidgetErrorBoundary } from './WidgetErrorBoundary';
import type { WidgetContext, WidgetAnchor, WidgetDefinition } from './types';

const ANCHOR_POSITIONS: Record<WidgetAnchor, string> = {
  'top-left': 'absolute top-3 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-14 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-20 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};

interface WidgetHostProps {
  ctx: WidgetContext;
}

export function WidgetHost({ ctx }: WidgetHostProps) {
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const { data: enabledWidgetIds } = useEnabledWidgets();

  const { byAnchor, sidebarLeft, sidebarRight } = useMemo(() => {
    const allRegistered = getWidgets();
    const enabledSet = enabledWidgetIds == null ? null : new Set(enabledWidgetIds);

    const definitions = allRegistered.filter(
      (w) => activeWidgets.has(w.id) && (enabledSet === null || enabledSet.has(w.id)),
    );

    const byAnchor: Record<string, WidgetDefinition[]> = {};
    const sidebarLeft: WidgetDefinition[] = [];
    const sidebarRight: WidgetDefinition[] = [];

    for (const w of definitions) {
      if (w.placement.mode === 'floating') {
        const anchor = w.placement.anchor;
        (byAnchor[anchor] ??= []).push(w);
      } else if (w.placement.side === 'left') {
        sidebarLeft.push(w);
      } else {
        sidebarRight.push(w);
      }
    }

    return { byAnchor, sidebarLeft, sidebarRight };
  }, [activeWidgets, enabledWidgetIds]);

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
      <WidgetSidebar side="left" widgets={sidebarLeft} ctx={ctx} />
      <WidgetSidebar side="right" widgets={sidebarRight} ctx={ctx} />
    </>
  );
}
