import { StyleColorPicker } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { CIRCLE_DEFAULTS } from './utils';
import type { BaseStyleEditorProps } from './types';

export function ClusterEditor({
  paint,
  builderConfig,
  onBuilderChange,
  t,
}: BaseStyleEditorProps) {
  const clusterColor = builderConfig.clusterColor
    ?? (typeof paint['circle-color'] === 'string' ? paint['circle-color'] as string : CIRCLE_DEFAULTS['circle-color']);
  const clusterTextColor = builderConfig.clusterTextColor ?? '#ffffff';

  return (
    <div className="space-y-3">
      <SliderRow
        label={t('style.cluster.radius')}
        value={builderConfig.clusterRadius ?? 48}
        min={1}
        max={120}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterRadius: val })}
      />
      <SliderRow
        label={t('style.cluster.maxZoom')}
        value={builderConfig.clusterMaxZoom ?? 14}
        min={0}
        max={22}
        step={1}
        format="zoom"
        onChange={(val) => onBuilderChange({ clusterMaxZoom: val })}
      />
      <StyleColorPicker
        label={t('style.cluster.color')}
        color={clusterColor}
        onChange={(hex) => onBuilderChange({ clusterColor: hex })}
      />
      <StyleColorPicker
        label={t('style.cluster.countColor')}
        color={clusterTextColor}
        onChange={(hex) => onBuilderChange({ clusterTextColor: hex })}
      />
      <SliderRow
        label={t('style.cluster.countSize')}
        value={builderConfig.clusterTextSize ?? 12}
        min={8}
        max={24}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterTextSize: val })}
      />
    </div>
  );
}

export default ClusterEditor;
