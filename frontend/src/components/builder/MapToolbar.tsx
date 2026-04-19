import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand, Ruler, PanelBottomOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface MapToolbarProps {
  aiAvailable?: boolean;
  showChat?: boolean;
  onToggleChat?: () => void;
}

/**
 * Floating horizontal toolbar on the map canvas.
 * Provides quick access to map interaction tools.
 */
export function MapToolbar({ aiAvailable, showChat, onToggleChat }: MapToolbarProps) {
  const { t } = useTranslation('builder');
  const measureActive = useWidgetStore((s) => s.activeWidgets.has('measurement'));
  const toggleMeasure = useWidgetStore((s) => s.toggle);

  const tools = useMemo(() => [
    {
      id: 'pan',
      icon: Hand,
      label: t('toolbar.pan', { defaultValue: 'Pan' }),
      shortcut: 'V',
      active: !measureActive,
      onClick: () => {
        if (measureActive) toggleMeasure('measurement');
      },
    },
    {
      id: 'measure',
      icon: Ruler,
      label: t('widgets.measurement.label', { defaultValue: 'Measure' }),
      shortcut: 'M',
      active: measureActive,
      onClick: () => { toggleMeasure('measurement'); },
    },
  ], [measureActive, toggleMeasure, t]);

  // Dock toggle — always available (dock has Attributes + Notes tabs even without AI)
  const dockTool = onToggleChat ? {
    id: 'dock',
    icon: PanelBottomOpen,
    label: t('tooltips.toggleDock', { defaultValue: 'Toggle dock' }),
    active: !!showChat,
    onClick: onToggleChat,
  } : null;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="absolute top-3 left-3 z-10 flex items-center bg-background/95 backdrop-blur-sm border rounded-lg shadow-md overflow-hidden">
        {tools.map((tool, i) => (
          <Tooltip key={tool.id}>
            <TooltipTrigger asChild>
              <button
                onClick={tool.onClick}
                className={cn(
                  'flex items-center justify-center h-[30px] w-[30px] transition-colors',
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
                <span className="ml-1.5 font-mono text-[10px] text-muted-foreground">{tool.shortcut}</span>
              )}
            </TooltipContent>
          </Tooltip>
        ))}

        {dockTool && (
          <>
            <div className="w-px h-4 bg-border/50 mx-0.5" />
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={dockTool.onClick}
                  className={cn(
                    'flex items-center justify-center h-[30px] w-[30px] transition-colors',
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
              </TooltipContent>
            </Tooltip>
          </>
        )}
      </div>
    </TooltipProvider>
  );
}
