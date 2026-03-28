import { useWidgetStore } from '@/stores/widget-store';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import type { WidgetContext, WidgetSlot, WidgetDefinition } from './types';

const SLOT_POSITIONS: Record<WidgetSlot, string> = {
  'top-left': 'absolute top-3 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-14 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-14 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
  'sidebar-bottom': '',
  'map-overlay': 'absolute bottom-0 left-0 right-0 z-20',
};

interface WidgetHostProps {
  ctx: WidgetContext;
}

export function WidgetHost({ ctx }: WidgetHostProps) {
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const definitions = getWidgets().filter((w) => activeWidgets.has(w.id));

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
        if (!className) return null;
        return (
          <div key={slot} className={className}>
            {widgets.map((w) => (
              <WidgetPanel
                key={w.id}
                def={w}
                onClose={() => useWidgetStore.getState().close(w.id)}
              >
                <w.component ctx={ctx} />
              </WidgetPanel>
            ))}
          </div>
        );
      })}
    </>
  );
}
