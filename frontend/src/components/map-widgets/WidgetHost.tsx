import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n/i18n';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import type { WidgetContext, WidgetSlot, WidgetDefinition } from './types';

const SLOT_POSITIONS: Record<WidgetSlot, string> = {
  'top-left': 'absolute top-3 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-14 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-20 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
  'sidebar-bottom': 'absolute bottom-4 left-4 z-10 flex flex-col gap-2',
  'map-overlay': 'absolute bottom-0 left-0 right-0 z-20',
};

/** Isolates widget crashes so one broken widget doesn't take down the host */
class WidgetErrorBoundary extends Component<
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
  const definitions = allRegistered.filter(
    (w) => activeWidgets.has(w.id) && (enabledSet === null || enabledSet.has(w.id)),
  );

  // Group by slot
  const bySlot = definitions.reduce<Record<string, WidgetDefinition[]>>((acc, w) => {
    const slot = w.slot;
    if (!acc[slot]) acc[slot] = [];
    acc[slot].push(w);
    return acc;
  }, {});

  const slots = Object.keys(SLOT_POSITIONS) as WidgetSlot[];

  return (
    <>
      {slots.map((slot) => {
        const widgets = bySlot[slot] ?? [];
        if (widgets.length === 0) return null;
        const className = SLOT_POSITIONS[slot];
        return (
          <div key={slot} className={className}>
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
    </>
  );
}
