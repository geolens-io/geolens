import { LayoutGrid } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getWidgets } from './registry';

export function WidgetToolbar() {
  const { t } = useTranslation('builder');
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const toggle = useWidgetStore((s) => s.toggle);
  const { data: enabledWidgetIds } = useEnabledWidgets();

  // Filter by admin-enabled widgets.
  // null/undefined = not configured or not loaded (show all), [] = none, [...ids] = only those
  const allRegistered = getWidgets();
  const widgets = enabledWidgetIds == null
    ? allRegistered
    : allRegistered.filter((w) => enabledWidgetIds.includes(w.id));

  if (widgets.length === 0) return null;

  const activeCount = widgets.filter((w) => activeWidgets.has(w.id)).length;

  return (
    <div className="absolute top-3 right-12 z-10">
      <Popover>
        <PopoverTrigger asChild>
          <button
            title={t('tooltips.widgets')}
            aria-label={t('tooltips.widgets')}
            className="flex items-center justify-center h-[30px] w-[30px] rounded-md bg-background/95 backdrop-blur-sm border shadow-md hover:bg-accent/50 transition-colors"
          >
            <LayoutGrid className="h-3.5 w-3.5 text-foreground/70" />
            {activeCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary text-[9px] font-medium text-primary-foreground">
                {activeCount}
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-48 p-1.5" sideOffset={4}>
          <div className="space-y-0.5">
            {widgets.map((w) => {
              const Icon = w.icon;
              const isActive = activeWidgets.has(w.id);
              return (
                <button
                  key={w.id}
                  onClick={() => toggle(w.id)}
                  className={`flex items-center gap-2 w-full rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    isActive
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="flex-1 truncate">{t(w.labelKey)}</span>
                  {isActive && (
                    <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
