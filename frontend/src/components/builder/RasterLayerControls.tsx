import { Slider } from '@/components/ui/slider';
import { useTranslation } from 'react-i18next';

interface RasterLayerControlsProps {
  opacity: number;
  onOpacityChange: (value: number) => void;
}

export function RasterLayerControls({ opacity, onOpacityChange }: RasterLayerControlsProps) {
  const { t } = useTranslation('builder');
  return (
    <div className="space-y-2 px-2 pb-2 pt-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {t('layerItem.opacity', { defaultValue: 'Opacity' })}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {Math.round(opacity * 100)}%
        </span>
      </div>
      <Slider
        min={0}
        max={1}
        step={0.01}
        value={[opacity]}
        onValueChange={([v]) => onOpacityChange(v)}
      />
    </div>
  );
}
