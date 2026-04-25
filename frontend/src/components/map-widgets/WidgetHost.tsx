import { useMemo } from 'react';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';
import { WidgetPanel } from './WidgetPanel';
import { WidgetErrorBoundary } from './WidgetErrorBoundary';
import type { WidgetContext, WidgetAnchor, WidgetDefinition } from './types';

// Anchor offsets account for map overlay controls:
// top-left: below MapToolbar (h-8 + top-3 = ~44px ≈ top-12)
// top-right: below MapToolbar row
// bottom-left: above ScaleControl (~24px) + EphemeralBadge (~32px)
// bottom-right: above NavigationControl
const ANCHOR_POSITIONS: Record<WidgetAnchor, string> = {
  'top-left': 'absolute top-12 left-3 z-10 flex flex-col gap-2',
  'top-right': 'absolute top-12 right-3 z-10 flex flex-col gap-2',
  'bottom-left': 'absolute bottom-14 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};

const ANCHORS = Object.keys(ANCHOR_POSITIONS) as WidgetAnchor[];

/** Partition active+enabled widgets by placement mode. Call once in the parent. */
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

    for (const w of definitions) {
      if (w.placement.mode === 'floating') {
        const anchor = w.placement.anchor;
        (byAnchor[anchor] ??= []).push(w);
      }
    }

    return { byAnchor };
  }, [activeWidgets, enabledWidgetIds]);
}

interface WidgetHostProps {
  byAnchor: Record<string, WidgetDefinition[]>;
  ctx: WidgetContext;
  /** Extra content rendered inside the top-left anchor (e.g., filter chips). */
  topLeftSlot?: React.ReactNode;
}

/** Renders floating widgets anchored to map corners */
export function WidgetHost({ byAnchor, ctx, topLeftSlot }: WidgetHostProps) {
  return (
    <>
      {ANCHORS.map((anchor) => {
        const widgets = byAnchor[anchor] ?? [];
        const slot = anchor === 'top-left' ? topLeftSlot : null;
        if (widgets.length === 0 && !slot) return null;
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
            {slot}
          </div>
        );
      })}
    </>
  );
}
