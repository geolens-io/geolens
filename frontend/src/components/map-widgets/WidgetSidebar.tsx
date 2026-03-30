import { cn } from '@/lib/utils';
import { WidgetPanel } from './WidgetPanel';
import { WidgetErrorBoundary } from './WidgetErrorBoundary';
import type { WidgetContext, WidgetDefinition } from './types';

interface WidgetSidebarProps {
  side: 'left' | 'right';
  /** Active sidebar widgets (filtered by store) -- rendered as content */
  widgets: WidgetDefinition[];
  ctx: WidgetContext;
}

/**
 * Slide-over panel that renders sidebar-mode widgets overlaying the map.
 * Always mounts when there are sidebar widget registrations to enable smooth
 * open/close animation via CSS translate.
 */
export function WidgetSidebar({ side, widgets, ctx }: WidgetSidebarProps) {
  const isRight = side === 'right';
  const hasActive = widgets.length > 0;

  return (
    <div
      className={cn(
        'absolute top-0 bottom-0 z-20 w-72',
        'flex flex-col overflow-hidden',
        'bg-background/95 backdrop-blur-sm shadow-lg',
        'transition-transform duration-200 ease-out',
        isRight ? 'right-0 border-l' : 'left-0 border-r',
        hasActive
          ? 'translate-x-0'
          : isRight
            ? 'translate-x-full'
            : '-translate-x-full',
        !hasActive && 'pointer-events-none',
      )}
    >
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {widgets.map((w) => (
          <WidgetPanel key={w.id} def={w}>
            <WidgetErrorBoundary widgetId={w.id}>
              <w.component ctx={ctx} />
            </WidgetErrorBoundary>
          </WidgetPanel>
        ))}
      </div>
    </div>
  );
}
