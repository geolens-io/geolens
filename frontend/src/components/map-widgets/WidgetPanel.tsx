import { X } from 'lucide-react';
import type { WidgetDefinition } from './types';

interface WidgetPanelProps {
  def: WidgetDefinition;
  onClose: () => void;
  children: React.ReactNode;
}

export function WidgetPanel({ def, onClose, children }: WidgetPanelProps) {
  const Icon = def.icon;

  return (
    <div className="rounded-lg border bg-background/95 backdrop-blur-sm shadow-lg min-w-48">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b">
        <Icon className="h-3.5 w-3.5 shrink-0 text-foreground/70" />
        <span className="text-xs font-medium flex-1">{def.label}</span>
        <button
          onClick={onClose}
          className="shrink-0 rounded p-0.5 hover:bg-accent/50 text-foreground/50 hover:text-foreground transition-colors"
          aria-label="Close widget"
        >
          <X className="h-3 w-3" />
        </button>
      </div>
      <div className="overflow-auto max-h-80 p-2.5">
        {children}
      </div>
    </div>
  );
}
