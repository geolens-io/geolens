import { Switch } from '@/components/ui/switch';
import { StyleColorPicker } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { getPaintValue } from './utils';

interface StrokeControlsProps {
  paint: Record<string, unknown>;
  strokeEnabled: boolean;
  onToggleStroke: () => void;
  colorKey: string;
  colorDefault: string;
  widthKey: string;
  widthDefault: number;
  onPaintProp: (key: string, value: unknown) => void;
  t: (key: string) => string;
}

export function StrokeControls({
  paint,
  strokeEnabled,
  onToggleStroke,
  colorKey,
  colorDefault,
  widthKey,
  widthDefault,
  onPaintProp,
  t,
}: StrokeControlsProps) {
  return (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
        <Switch
          checked={strokeEnabled}
          onCheckedChange={onToggleStroke}
          aria-label={t('style.toggleStroke')}
          className="scale-75 mt-2"
        />
      </div>
      {strokeEnabled && (
        <>
          <StyleColorPicker
            label={t('style.color')}
            color={getPaintValue(paint, colorKey, colorDefault)}
            onChange={(hex) => onPaintProp(colorKey, hex)}
          />
          <SliderRow
            label={t('style.width')}
            value={getPaintValue(paint, widthKey, widthDefault)}
            min={0}
            max={10}
            step={0.5}
            format="px"
            onChange={(val) => onPaintProp(widthKey, val)}
          />
        </>
      )}
    </>
  );
}
