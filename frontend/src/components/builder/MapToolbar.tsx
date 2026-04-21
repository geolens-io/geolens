import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand, Ruler, PanelBottomOpen, Layers } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface MapToolbarProps {
  showChat?: boolean;
  onToggleChat?: () => void;
}

/**
 * Floating horizontal toolbar on the map canvas.
 * Provides quick access to map interaction tools.
 */
export function MapToolbar({ showChat, onToggleChat }: MapToolbarProps) {
  const { t } = useTranslation('builder');
  const measureActive = useWidgetStore((s) => s.activeWidgets.has('measurement'));
  const legendActive = useWidgetStore((s) => s.activeWidgets.has('legend'));
  const toggle = useWidgetStore((s) => s.toggle);

  const tools = useMemo(() => [
    {
      id: 'pan',
      icon: Hand,
      label: t('toolbar.pan', { defaultValue: 'Pan' }),
      shortcut: 'V',
      active: !measureActive,
      onClick: () => {
        if (measureActive) toggle('measurement');
      },
    },
    {
      id: 'measure',
      icon: Ruler,
      label: t('widgets.measurement.label', { defaultValue: 'Measure' }),
      shortcut: 'M',
      active: measureActive,
      onClick: () => { toggle('measurement'); },
    },
  ], [measureActive, toggle, t]);

  // Dock toggle — always available (dock has Attributes + Notes tabs even without AI)
  const dockTool = onToggleChat ? {
    id: 'dock',
    icon: PanelBottomOpen,
    label: t('tooltips.toggleDock', { defaultValue: 'Toggle dock' }),
    shortcut: 'D',
    active: !!showChat,
    onClick: onToggleChat,
  } : null;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5">
        {/* Tool mode buttons (Pan / Measure) */}
        <div className="flex items-center bg-background/95 backdrop-blur-sm border rounded-lg shadow-md overflow-hidden">
          {tools.map((tool, i) => (
            <Tooltip key={tool.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={tool.onClick}
                  className={cn(
                    'flex items-center justify-center h-8 w-8 transition-colors',
                    tool.active
                      ? 'bg-signature-soft text-signature'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                    i > 0 && 'border-l border-border/50',
                  )}
                  aria-label={tool.label}
                  aria-pressed={tool.active}
                >
                  <tool.icon className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                {tool.label}
                {tool.shortcut && (
                  <span className="ms-1.5 font-mono text-2xs text-muted-foreground">{tool.shortcut}</span>
                )}
              </TooltipContent>
            </Tooltip>
          ))}
        </div>

        {/* Panel toggles — separate from tool modes (panel visibility, not map tools) */}
        <div className="flex items-center bg-background/95 backdrop-blur-sm border rounded-lg shadow-md overflow-hidden">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => toggle('legend')}
                className={cn(
                  'flex items-center justify-center h-8 w-8 transition-colors',
                  legendActive
                    ? 'bg-signature-soft text-signature'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
                aria-label={t('widgets.legend.label', { defaultValue: 'Legend' })}
                aria-pressed={legendActive}
              >
                <Layers className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {t('widgets.legend.label', { defaultValue: 'Legend' })}
              <span className="ms-1.5 font-mono text-2xs text-muted-foreground">L</span>
            </TooltipContent>
          </Tooltip>
          {dockTool && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={dockTool.onClick}
                  className={cn(
                    'flex items-center justify-center h-8 w-8 border-l border-border/50 transition-colors',
                    dockTool.active
                      ? 'bg-signature-soft text-signature'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                  aria-label={dockTool.label}
                  aria-pressed={dockTool.active}
                >
                  <dockTool.icon className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                {dockTool.label}
                {dockTool.shortcut && (
                  <span className="ms-1.5 font-mono text-2xs text-muted-foreground">{dockTool.shortcut}</span>
                )}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
