import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { normalizeBasemapConfig } from '@/lib/basemap-utils';
import type {
  MapBasemapConfig,
  MapBasemapLandWaterTone,
  MapBasemapReliefContrast,
  MapBasemapVisibilityMode,
} from '@/types/api';

interface BasemapAppearanceControlsProps {
  value: MapBasemapConfig | null | undefined;
  showBasemapLabels: boolean;
  onChange: (value: MapBasemapConfig) => void;
  onShowBasemapLabelsChange?: (show: boolean) => void;
}

const VISIBILITY_OPTIONS: Array<{ value: MapBasemapVisibilityMode; label: string }> = [
  { value: 'full', label: 'Full' },
  { value: 'subtle', label: 'Subtle' },
  { value: 'hidden', label: 'Hidden' },
];

const LAND_WATER_OPTIONS: Array<{ value: MapBasemapLandWaterTone; label: string }> = [
  { value: 'default', label: 'Default' },
  { value: 'muted', label: 'Muted' },
  { value: 'contrast', label: 'Contrast' },
  { value: 'monochrome', label: 'Monochrome' },
];

const RELIEF_OPTIONS: Array<{ value: 'none' | MapBasemapReliefContrast; label: string }> = [
  { value: 'none', label: 'Default' },
  { value: 'soft', label: 'Soft' },
  { value: 'standard', label: 'Standard' },
  { value: 'strong', label: 'Strong' },
];

function ControlSelect<TValue extends string>({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: TValue;
  options: Array<{ value: TValue; label: string }>;
  onChange: (value: TValue) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_7rem] items-center gap-2">
      <Label htmlFor={id} className="min-w-0 truncate text-xs text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={(next) => onChange(next as TValue)}>
        <SelectTrigger id={id} aria-label={label} className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value} className="text-xs">
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function BasemapAppearanceControls({
  value,
  showBasemapLabels,
  onChange,
  onShowBasemapLabelsChange,
}: BasemapAppearanceControlsProps) {
  const { t } = useTranslation('builder');
  const config = useMemo(
    () => normalizeBasemapConfig(value, showBasemapLabels),
    [showBasemapLabels, value],
  );

  function update(next: Partial<MapBasemapConfig>) {
    onChange({ ...config, ...next });
  }

  function handleLabelModeChange(labelMode: MapBasemapVisibilityMode) {
    update({ label_mode: labelMode });
    onShowBasemapLabelsChange?.(labelMode !== 'hidden');
  }

  return (
    <div className="space-y-3 border-t border-border/60 px-2 pt-3">
      <div className="flex items-center justify-between gap-3">
        <Label className="text-sm font-medium">
          {t('basemap.appearance', { defaultValue: 'Appearance' })}
        </Label>
      </div>

      <div className="space-y-2">
        <ControlSelect
          id="basemap-label-mode"
          label={t('basemap.labels', { defaultValue: 'Labels' })}
          value={config.label_mode}
          options={VISIBILITY_OPTIONS}
          onChange={handleLabelModeChange}
        />
        <ControlSelect
          id="basemap-road-visibility"
          label={t('basemap.roads', { defaultValue: 'Roads' })}
          value={config.road_visibility}
          options={VISIBILITY_OPTIONS}
          onChange={(road_visibility) => update({ road_visibility })}
        />
        <ControlSelect
          id="basemap-boundary-visibility"
          label={t('basemap.boundaries', { defaultValue: 'Boundaries' })}
          value={config.boundary_visibility}
          options={VISIBILITY_OPTIONS}
          onChange={(boundary_visibility) => update({ boundary_visibility })}
        />
        <ControlSelect
          id="basemap-land-water-tone"
          label={t('basemap.landWater', { defaultValue: 'Land / water' })}
          value={config.land_water_tone}
          options={LAND_WATER_OPTIONS}
          onChange={(land_water_tone) => update({ land_water_tone })}
        />
        <ControlSelect
          id="basemap-relief-contrast"
          label={t('basemap.relief', { defaultValue: 'Relief' })}
          value={config.relief_contrast ?? 'none'}
          options={RELIEF_OPTIONS}
          onChange={(relief) => update({ relief_contrast: relief === 'none' ? null : relief })}
        />
      </div>

      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="basemap-buildings" className="text-xs text-muted-foreground">
          {t('basemap.buildings', { defaultValue: 'Buildings' })}
        </Label>
        <Switch
          id="basemap-buildings"
          size="sm"
          checked={config.building_visibility}
          onCheckedChange={(building_visibility) => update({ building_visibility })}
          aria-label={t('basemap.buildings', { defaultValue: 'Buildings' })}
        />
      </div>
    </div>
  );
}
