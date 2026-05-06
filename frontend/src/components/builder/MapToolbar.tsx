import { useMemo, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand, Ruler, Layers, FileJson } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { getEnabledWidgetDefinitions } from '@/components/map-widgets';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * Floating toolbar centered at the top of the map canvas.
 * Grouped into semantic sections: navigation | widgets.
 */
interface MapToolbarProps {
  onStyleJsonClick?: () => void;
}

export function MapToolbar({ onStyleJsonClick }: MapToolbarProps) {
  const { t } = useTranslation('builder');
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const toggle = useWidgetStore((s) => s.toggle);
  const close = useWidgetStore((s) => s.close);
  const enabledWidgetsQuery = useEnabledWidgets();
  const enabledWidgetIds = useMemo(
    () => enabledWidgetsQuery.data ?? (enabledWidgetsQuery.isLoading ? [] : null),
    [enabledWidgetsQuery.data, enabledWidgetsQuery.isLoading],
  );
  const availableWidgets = useMemo(
    () => getEnabledWidgetDefinitions(enabledWidgetIds),
    [enabledWidgetIds],
  );
  const measurementWidget = availableWidgets.find((widget) => widget.id === 'measurement');
  const legendWidget = availableWidgets.find((widget) => widget.id === 'legend');
  const LegendIcon = legendWidget?.icon ?? Layers;
  const measureActive = !!measurementWidget && activeWidgets.has('measurement');
  const legendActive = !!legendWidget && activeWidgets.has('legend');

  const navTools = useMemo(() => {
    const tools: Array<{
      id: string;
      icon: ComponentType<{ className?: string }>;
      label: string;
      shortcut: string;
      active: boolean;
      onClick: () => void;
    }> = [{
      id: 'pan',
      icon: Hand,
      label: t('toolbar.pan', { defaultValue: 'Pan' }),
      shortcut: 'V',
      active: !measureActive,
      onClick: () => { if (activeWidgets.has('measurement')) close('measurement'); },
    }];
    if (measurementWidget) {
      tools.push({
        id: 'measure',
        icon: measurementWidget.icon ?? Ruler,
        label: t('widgets.measurement.label', { defaultValue: 'Measure' }),
        shortcut: 'M',
        active: measureActive,
        onClick: () => { toggle('measurement'); },
      });
    }
    return tools;
  }, [activeWidgets, close, measureActive, measurementWidget, toggle, t]);

  return (
    <TooltipProvider delayDuration={300}>
      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[5]">
        <div className="inline-flex items-center gap-0.5 p-0.5 bg-background/95 backdrop-blur-sm border rounded-lg shadow-md">
          {/* Navigation tools (Pan / Measure) */}
          {navTools.map((tool) => (
            <Tooltip key={tool.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={tool.onClick}
                  className={cn(
                    'flex items-center justify-center h-7 w-7 rounded-md transition-colors',
                    tool.active
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                  aria-label={tool.label}
                  aria-pressed={tool.active}
                >
                  <tool.icon className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                {tool.label}
                <span className="ms-1.5 font-mono text-2xs text-muted-foreground">{tool.shortcut}</span>
              </TooltipContent>
            </Tooltip>
          ))}

          {legendWidget && (
            <>
              {/* Divider */}
              <div className="w-px h-4 bg-border mx-0.5" />

              {/* Widget toggles (Legend) */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => toggle('legend')}
                    className={cn(
                      'flex items-center justify-center h-7 w-7 rounded-md transition-colors',
                      legendActive
                        ? 'bg-foreground text-background'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                    )}
                    aria-label={t('widgets.legend.label', { defaultValue: 'Legend' })}
                    aria-pressed={legendActive}
                  >
                    <LegendIcon className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs">
                  {t('widgets.legend.label', { defaultValue: 'Legend' })}
                  <span className="ms-1.5 font-mono text-2xs text-muted-foreground">L</span>
                </TooltipContent>
              </Tooltip>
            </>
          )}

          {onStyleJsonClick && (
            <>
              <div className="w-px h-4 bg-border mx-0.5" />
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={onStyleJsonClick}
                    className="flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label={t('toolbar.styleJson', { defaultValue: 'Style JSON' })}
                  >
                    <FileJson className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs">
                  {t('toolbar.styleJson', { defaultValue: 'Style JSON' })}
                </TooltipContent>
              </Tooltip>
            </>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
