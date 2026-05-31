import { memo, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { usePluginStore } from '@/stores/map-plugin-store';
import type { PluginDefinition } from './types';

interface PluginPanelProps {
  def: PluginDefinition;
  children: ReactNode;
}

/**
 * Container for an open map builder plugin.
 *
 * Renders the plugin's icon, translated label, and close button in a header
 * row with the plugin body in a scrollable region beneath. Closing the panel
 * dispatches `usePluginStore.close()` to remove it from the open-plugin set.
 *
 * Used internally by {@link PluginHost} when rendering each visible widget
 * from the registry; plugin authors do not import this directly.
 */
export const PluginPanel = memo(function PluginPanel({ def, children }: PluginPanelProps) {
  const { t } = useTranslation('builder');
  const Icon = def.icon;

  return (
    <div className="rounded-lg border bg-background/95 backdrop-blur-sm shadow-lg min-w-48">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b">
        <Icon className="h-3.5 w-3.5 shrink-0 text-foreground/70" />
        <span className="text-xs font-medium flex-1">{t(def.labelKey)}</span>
        <button
          onClick={() => usePluginStore.getState().close(def.id)}
          className="shrink-0 rounded p-1 hover:bg-accent/50 text-foreground/50 hover:text-foreground transition-colors min-h-6 min-w-6 flex items-center justify-center"
          aria-label={t('plugins.closePlugin')}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
      <div className="overflow-auto max-h-80 p-2.5">
        {children}
      </div>
    </div>
  );
});
