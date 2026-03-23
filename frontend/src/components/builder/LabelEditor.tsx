import { useTranslation } from 'react-i18next';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { StyleColorPicker } from './StyleColorPicker';
import { MAP_COLORS } from '@/lib/map-colors';
import type { LabelConfig } from '@/types/api';

interface LabelEditorProps {
  columns: { name: string; type: string }[];
  labelConfig: LabelConfig | null;
  onLabelChange: (config: LabelConfig | null) => void;
}

const DEFAULTS: LabelConfig = {
  column: '',
  fontSize: 12,
  textColor: MAP_COLORS.label.color,
  haloColor: MAP_COLORS.label.halo,
  haloWidth: 1.5,
};

export function LabelEditor({ columns, labelConfig, onLabelChange }: LabelEditorProps) {
  const { t } = useTranslation('builder');
  const isOn = labelConfig !== null;

  function handleToggle(checked: boolean) {
    if (checked) {
      onLabelChange({
        ...DEFAULTS,
        column: columns[0]?.name ?? '',
      });
    } else {
      onLabelChange(null);
    }
  }

  function update(partial: Partial<LabelConfig>) {
    if (!labelConfig) return;
    onLabelChange({ ...labelConfig, ...partial });
  }

  return (
    <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">{t('labels.title')}</Label>
        <Switch checked={isOn} onCheckedChange={handleToggle} />
      </div>

      {isOn && labelConfig && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('labels.column')}</span>
            <Select
              value={labelConfig.column}
              onValueChange={(val) => update({ column: val })}
            >
              <SelectTrigger className="h-7 text-xs flex-1">
                <SelectValue placeholder={t('labels.selectColumn')} />
              </SelectTrigger>
              <SelectContent>
                {columns.map((col) => (
                  <SelectItem key={col.name} value={col.name} className="text-xs">
                    {col.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('labels.fontSize')}</span>
            <Slider
              value={[labelConfig.fontSize]}
              min={8}
              max={24}
              step={1}
              onValueChange={([v]) => update({ fontSize: v })}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">
              {labelConfig.fontSize}px
            </span>
          </div>

          <StyleColorPicker
            label={t('labels.textColor')}
            color={labelConfig.textColor}
            onChange={(hex) => update({ textColor: hex })}
          />

          <StyleColorPicker
            label={t('labels.haloColor')}
            color={labelConfig.haloColor}
            onChange={(hex) => update({ haloColor: hex })}
          />

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('labels.haloWidth')}</span>
            <Slider
              value={[labelConfig.haloWidth ?? 1.5]}
              min={0}
              max={4}
              step={0.5}
              onValueChange={([v]) => update({ haloWidth: v })}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">
              {labelConfig.haloWidth ?? 1.5}px
            </span>
          </div>

          <div className="text-xs font-medium mt-2 pt-2 border-t">{t('labels.zoomRange')}</div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('labels.minZoom')}</span>
            <Slider
              value={[labelConfig.minZoom ?? 0]}
              min={0}
              max={(labelConfig.maxZoom ?? 22) - 1}
              step={1}
              onValueChange={([v]) => update({ minZoom: v })}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">
              {labelConfig.minZoom ?? 0}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('labels.maxZoom')}</span>
            <Slider
              value={[labelConfig.maxZoom ?? 22]}
              min={(labelConfig.minZoom ?? 0) + 1}
              max={22}
              step={1}
              onValueChange={([v]) => update({ maxZoom: v })}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">
              {labelConfig.maxZoom ?? 22}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
