import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n/i18n';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import { WidgetSidebar } from './WidgetSidebar';
import type { WidgetContext, WidgetAnchor, WidgetDefinition } from './types';

const ANCHOR_POSITIONS: Record<WidgetAnchor, string> = {
  'top-left': 'absolute top-3 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-14 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-20 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};

/** Isolates widget crashes so one broken widget doesn't take down the host */
export class WidgetErrorBoundary extends Component<
  { widgetId: string; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Widget "${this.props.widgetId}" crashed:`, error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-2.5 text-xs text-destructive">
          {i18n.t('builder:widgets.widgetError')}
        </div>
      );
    }
    return this.props.children;
  }
}

interface WidgetHostProps {
  ctx: WidgetContext;
}

export function WidgetHost({ ctx }: WidgetHostProps) {
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const { data: enabledWidgetIds } = useEnabledWidgets();

  // Filter: must be active (in store) AND admin-enabled (in settings)
  // null/undefined = not configured (show all), [] = none, [...ids] = only those
  const allRegistered = getWidgets();
  const enabledSet = enabledWidgetIds == null ? null : new Set(enabledWidgetIds);

  // Active + enabled definitions
  const definitions = allRegistered.filter(
    (w) => activeWidgets.has(w.id) && (enabledSet === null || enabledSet.has(w.id)),
  );

  // All enabled registrations (for always-render sidebar pattern)
  const allEnabled = allRegistered.filter(
    (w) => enabledSet === null || enabledSet.has(w.id),
  );

  // Partition active widgets by placement mode
  const floating = definitions.filter((w) => w.placement.mode === 'floating');
  const sidebarLeft = definitions.filter(
    (w) => w.placement.mode === 'sidebar' && w.placement.side === 'left',
  );
  const sidebarRight = definitions.filter(
    (w) => w.placement.mode === 'sidebar' && w.placement.side === 'right',
  );

  // All enabled sidebar registrations (for always-render containers)
  const allSidebarLeft = allEnabled.filter(
    (w) => w.placement.mode === 'sidebar' && w.placement.side === 'left',
  );
  const allSidebarRight = allEnabled.filter(
    (w) => w.placement.mode === 'sidebar' && w.placement.side === 'right',
  );

  // Group floating widgets by anchor
  const byAnchor = floating.reduce<Record<string, WidgetDefinition[]>>((acc, w) => {
    if (w.placement.mode !== 'floating') return acc;
    const anchor = w.placement.anchor;
    if (!acc[anchor]) acc[anchor] = [];
    acc[anchor].push(w);
    return acc;
  }, {});

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
              <WidgetPanel
                key={w.id}
                def={w}
                onClose={() => useWidgetStore.getState().close(w.id)}
              >
                <WidgetErrorBoundary widgetId={w.id}>
                  <w.component ctx={ctx} />
                </WidgetErrorBoundary>
              </WidgetPanel>
            ))}
          </div>
        );
      })}
      {allSidebarLeft.length > 0 && (
        <WidgetSidebar
          side="left"
          widgets={sidebarLeft}
          allSidebarWidgets={allSidebarLeft}
          ctx={ctx}
        />
      )}
      {allSidebarRight.length > 0 && (
        <WidgetSidebar
          side="right"
          widgets={sidebarRight}
          allSidebarWidgets={allSidebarRight}
          ctx={ctx}
        />
      )}
    </>
  );
}
