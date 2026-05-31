import type { PluginContext } from './types';
import type { PluginDefinition } from './registry';
import { useTranslation } from 'react-i18next';

interface PluginPanelProps {
  mapId: string;
  plugins: { defs: PluginDefinition[]; active: Set<string> };
  context: PluginContext;
}

export function PluginPanel({ mapId, plugins, context }: PluginPanelProps) {
  const { t } = useTranslation('builder');
  return (
    <div data-testid="plugin-panel">
      {plugins.defs.map((def) => {
        const Comp = def.component;
        return (
          <div key={def.id} className="plugin-item">
            {Comp && <Comp context={context} />}
          </div>
        );
      })}
    </div>
  );
}
