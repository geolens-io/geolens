import { useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { StyleColorPicker } from './StyleColorPicker';
import { ZoomExpressionEditor } from './ZoomExpressionEditor';
import { MAP_COLORS } from '@/lib/map-colors';
import { cn } from '@/lib/utils';
import type { LabelConfig } from '@/types/api';

interface LabelEditorProps {
  columns: { name: string; type: string }[];
  labelConfig: LabelConfig | null;
  onLabelChange: (config: LabelConfig | null) => void;
  geometryType?: string | null;
}

const DEFAULTS: LabelConfig = {
  column: '',
  fontSize: 12,
  textColor: MAP_COLORS.label.color,
  haloColor: MAP_COLORS.label.halo,
  haloWidth: 1.5,
};

const PLACEMENT_OPTIONS = [
  { value: 'point', labelKey: 'labels.placementPoint' },
  { value: 'line', labelKey: 'labels.placementLine' },
  { value: 'line-center', labelKey: 'labels.placementLineCenter' },
] as const;

const ANCHOR_OPTIONS = [
  { value: 'center', labelKey: 'labels.anchorCenter' },
  { value: 'top', labelKey: 'labels.anchorTop' },
  { value: 'bottom', labelKey: 'labels.anchorBottom' },
  { value: 'left', labelKey: 'labels.anchorLeft' },
  { value: 'right', labelKey: 'labels.anchorRight' },
  { value: 'top-left', label: 'Top Left' },
  { value: 'top-right', label: 'Top Right' },
  { value: 'bottom-left', label: 'Bottom Left' },
  { value: 'bottom-right', label: 'Bottom Right' },
] as const;

export function LabelEditor({ columns, labelConfig, onLabelChange, geometryType }: LabelEditorProps) {
  const { t } = useTranslation('builder');
  const isOn = labelConfig !== null;
  const isLine = (geometryType ?? '').toUpperCase().includes('LINE');

  const filteredPlacements = useMemo(() => {
    const gt = (geometryType ?? '').toUpperCase();
    if (gt.includes('LINE')) return PLACEMENT_OPTIONS;
    return PLACEMENT_OPTIONS.filter(p => p.value === 'point');
  }, [geometryType]);

  // B-017/LB-01: Sync from prop so the ref survives unmount/remount cycles
  const lastConfigRef = useRef<LabelConfig | null>(labelConfig);
  if (labelConfig) lastConfigRef.current = labelConfig;

  function handleToggle(checked: boolean) {
    if (checked) {
      // Restore last known config or use defaults
      if (lastConfigRef.current) {
        onLabelChange(lastConfigRef.current);
      } else {
        const firstColumn = columns[0]?.name;
        // Without a column, the upstream handler normalizes config back to null
        // (empty column = non-functional config). That made the Switch appear
        // dead from the user's perspective. Bail out early instead so the Switch
        // stays off until columns are available — caller can show a toast or
        // disabled state if needed (LB-DEBUG: Phase 261 audit).
        if (!firstColumn) {
          return;
        }
        onLabelChange({
          ...DEFAULTS,
          column: firstColumn,
          placement: isLine ? 'line' : 'point',
        });
      }
    } else {
      onLabelChange(null);
    }
  }

  function update(partial: Partial<LabelConfig>) {
    if (!labelConfig) return;
    onLabelChange({ ...labelConfig, ...partial });
  }

  const placement = labelConfig?.placement ?? (isLine ? 'line' : 'point');
  const isPointPlacement = placement === 'point';

  return (
    <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">{t('labels.title')}</Label>
        <Switch
          checked={isOn}
          onCheckedChange={handleToggle}
          disabled={!isOn && columns.length === 0}
          aria-disabled={!isOn && columns.length === 0}
          title={!isOn && columns.length === 0 ? t('labels.noColumns', { defaultValue: 'No columns available to label' }) : undefined}
        />
      </div>

      {isOn && labelConfig && (
        <>
          {/* Column selector */}
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

          <ZoomExpressionEditor
            label={t('labels.fontSize')}
            value={labelConfig.fontSize ?? 12}
            defaultValue={12}
            min={8}
            max={24}
            step={1}
            format="px"
            onChange={(val) => update({ fontSize: val })}
          />

          {/* Colors */}
          <StyleColorPicker
            label={t('labels.textColor')}
            color={labelConfig.textColor ?? '#111827'}
            onChange={(hex) => update({ textColor: hex })}
          />

          <ZoomExpressionEditor
            label={t('labels.textOpacity', { defaultValue: 'Text opacity' })}
            value={labelConfig.textOpacity ?? 1}
            defaultValue={1}
            min={0}
            max={1}
            step={0.05}
            format="percent"
            onChange={(val) => update({ textOpacity: val })}
          />

          <StyleColorPicker
            label={t('labels.haloColor')}
            color={labelConfig.haloColor ?? '#ffffff'}
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
            <span className="text-xs text-muted-foreground w-10 text-end">
              {labelConfig.haloWidth ?? 1.5}px
            </span>
          </div>

          {/* Placement presets */}
          <div className="text-xs font-medium mt-2 pt-2 border-t">{t('labels.placement')}</div>
          <div className="flex gap-1">
            {filteredPlacements.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={cn(
                  'flex-1 cursor-pointer px-2 py-1 text-xs rounded border transition-colors',
                  placement === opt.value
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
                )}
                onClick={() => update({ placement: opt.value })}
              >
                {t(opt.labelKey, { defaultValue: opt.value })}
              </button>
            ))}
          </div>

          {/* Anchor (only for point placement) */}
          {isPointPlacement && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-20">{t('labels.anchor')}</span>
              <Select
                value={labelConfig.textAnchor ?? 'center'}
                onValueChange={(val) => update({ textAnchor: val as LabelConfig['textAnchor'] })}
              >
                <SelectTrigger className="h-7 text-xs flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ANCHOR_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value} className="text-xs">
                      {'labelKey' in opt ? t(opt.labelKey, { defaultValue: opt.value }) : opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Text offset (only for point placement) */}
          {isPointPlacement && (
            <>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20">{t('labels.offsetX')}</span>
                <Slider
                  value={[labelConfig.textOffset?.[0] ?? 0]}
                  min={-3}
                  max={3}
                  step={0.1}
                  onValueChange={([v]) => update({ textOffset: [v, labelConfig.textOffset?.[1] ?? 0] })}
                  className="flex-1"
                />
                <span className="text-xs text-muted-foreground w-10 text-end">
                  {(labelConfig.textOffset?.[0] ?? 0).toFixed(1)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20">{t('labels.offsetY')}</span>
                <Slider
                  value={[labelConfig.textOffset?.[1] ?? 0]}
                  min={-3}
                  max={3}
                  step={0.1}
                  onValueChange={([v]) => update({ textOffset: [labelConfig.textOffset?.[0] ?? 0, v] })}
                  className="flex-1"
                />
                <span className="text-xs text-muted-foreground w-10 text-end">
                  {(labelConfig.textOffset?.[1] ?? 0).toFixed(1)}
                </span>
              </div>
            </>
          )}

          {/* Allow overlap */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{t('labels.allowOverlap')}</span>
            <Switch
              checked={labelConfig.allowOverlap ?? false}
              onCheckedChange={(v) => update({ allowOverlap: v })}
              className="scale-75"
            />
          </div>

          {/* Zoom range */}
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
            <span className="text-xs text-muted-foreground w-10 text-end">
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
            <span className="text-xs text-muted-foreground w-10 text-end">
              {labelConfig.maxZoom ?? 22}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
