import { useMemo, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand, Ruler, Layers, FileJson } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useEnabledPlugins } from '@/hooks/use-settings';
import { getEnabledPluginDefinitions } from '@/components/map-plugins';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * Floating toolbar centered at the top of the map canvas.
 * Grouped into semantic sections: navigation | plugins.
 */
interface MapToolbarProps {
  onStyleJsonClick?: () => void;
}

export function MapToolbar({ onStyleJsonClick }: MapToolbarProps) {
  const { t } = useTranslation('builder');
  const activePlugins = usePluginStore((s) => s.activePlugins);
  const toggle = usePluginStore((s) => s.toggle);
  const close = usePluginStore((s) => s.close);
  const enabledPluginsQuery = useEnabledPlugins();
  const enabledPluginIds = useMemo(
    () => enabledPluginsQuery.data ?? (enabledPluginsQuery.isLoading ? [] : null),
    [enabledPluginsQuery.data, enabledPluginsQuery.isLoading],
  );
  const availablePlugins = useMemo(
    () => getEnabledPluginDefinitions(enabledPluginIds),
    [enabledPluginIds],
  );
  const measurementPlugin = availablePlugins.find((plugin) => plugin.id === 'measurement');
  const legendPlugin = availablePlugins.find((plugin) => plugin.id === 'legend');
  const LegendIcon = legendPlugin?.icon ?? Layers;
  const measureActive = !!measurementPlugin && activePlugins.has('measurement');
  const legendActive = !!legendPlugin && activePlugins.has('legend');

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
      onClick: () => { if (activePlugins.has('measurement')) close('measurement'); },
    }];
    if (measurementPlugin) {
      tools.push({
        id: 'measure',
        icon: measurementPlugin.icon ?? Ruler,
        label: t('widgets.measurement.label', { defaultValue: 'Measure' }),
        shortcut: 'M',
        active: measureActive,
        onClick: () => { toggle('measurement'); },
      });
    }
    return tools;
  }, [activePlugins, close, measureActive, measurementPlugin, toggle, t]);

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
                    'flex cursor-pointer items-center justify-center h-7 w-7 rounded-md transition-colors',
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

          {legendPlugin && (
            <>
              {/* Divider */}
              <div className="w-px h-4 bg-border mx-0.5" />

              {/* Plugin toggles (Legend) */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => toggle('legend')}
                    className={cn(
                      'flex cursor-pointer items-center justify-center h-7 w-7 rounded-md transition-colors',
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
                    className="flex cursor-pointer items-center justify-center h-7 w-7 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
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
