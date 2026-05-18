import { Filter, Layers, Type, Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ComponentType, SVGProps } from 'react';
import type { MapLayerResponse } from '@/types/api';

/**
 * SublayerConfigIndicators — Phase 1051 UX-02.
 *
 * Replaces the per-row opacity slider in basemap sublayer rows
 * (UnifiedStackPanel SublayerRow). Renders 0–4 small Lucide-icon badges
 * reflecting live config state:
 *   • Labels    — label_config.column set
 *   • Filter    — filter is a non-empty array
 *   • DataDriven — any paint value is an expression (array)
 *   • OpacityModified — layer.opacity !== 1
 *
 * Opacity editing remains in the LayerEditorPanel flyout opened by
 * clicking the sublayer row (i.e. this component is purely a status
 * surface; it does NOT introduce a duplicate opacity affordance).
 *
 * Per UI-SPEC §UX-02: render nothing when no condition is met.
 */

interface Props {
  layer: MapLayerResponse | null;
}

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

interface Indicator {
  id: 'labels' | 'filter' | 'dataDriven' | 'opacity';
  Icon: IconComponent;
  label: string;
}

export function SublayerConfigIndicators({ layer }: Props) {
  const { t } = useTranslation('builder');

  if (!layer) return null;

  const indicators: Indicator[] = [];

  if (layer.label_config?.column) {
    indicators.push({
      id: 'labels',
      Icon: Type,
      label: t('indicators.labels', { defaultValue: 'Labels enabled' }),
    });
  }

  if (Array.isArray(layer.filter) && layer.filter.length > 0) {
    indicators.push({
      id: 'filter',
      Icon: Filter,
      label: t('indicators.filter', { defaultValue: 'Filter applied' }),
    });
  }

  const paint = layer.paint ?? {};
  const dataDriven = Object.values(paint).some((value) => Array.isArray(value));
  if (dataDriven) {
    indicators.push({
      id: 'dataDriven',
      Icon: Zap,
      label: t('indicators.dataDriven', { defaultValue: 'Data-driven style' }),
    });
  }

  if (typeof layer.opacity === 'number' && layer.opacity !== 1) {
    indicators.push({
      id: 'opacity',
      Icon: Layers,
      label: t('indicators.opacityModified', { defaultValue: 'Opacity adjusted' }),
    });
  }

  if (indicators.length === 0) return null;

  return (
    <div className="flex items-center gap-1">
      {indicators.slice(0, 4).map(({ id, Icon, label }) => (
        <span
          key={id}
          title={label}
          className="inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]"
        >
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span className="sr-only">{label}</span>
        </span>
      ))}
    </div>
  );
}
