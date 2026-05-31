import { useTranslation } from 'react-i18next';
import type { PluginContext } from '../types';

export function LegendPlugin({ context }: { context: PluginContext }) {
  const { t } = useTranslation('builder');
  const layerId = `legend-widget-${0}`;
  return (
    <div data-testid="legend-plugin">
      <span>{layerId}</span>
      <span>{t('widgets.legend.label')}</span>
    </div>
  );
}
