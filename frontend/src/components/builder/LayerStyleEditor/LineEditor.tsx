import { StyleColorPicker } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { LineGradientControls } from '../LineGradientControls';
import { ZoomExpressionEditor } from '../ZoomExpressionEditor';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { LINE_DASH_PRESETS, LINE_DASH_SERIALIZED, LINE_DEFAULTS, getPaintValue, getEditableNumericPaintValue } from './utils';
import type { BaseStyleEditorProps } from './types';
import type { BuilderStyleConfig } from '@/types/api';

export function LineEditor({
  layer,
  paint,
  isDataDriven,
  styleConfig,
  onPaintProp,
  onPaintChange,
  onLayoutChange,
  onBuilderChange,
  t,
}: BaseStyleEditorProps) {
  const isWidthDataDriven = isDataDriven && layer.style_config?.target === 'width';
  const builder = styleConfig?.builder ?? {};
  const isArrow = styleConfig?.render_mode === 'arrow';
  const arrowColor = (builder as BuilderStyleConfig).arrowColor
    ?? (typeof paint['line-color'] === 'string' ? paint['line-color'] as string : LINE_DEFAULTS['line-color']);

  return (
    <>
      <div className="text-xs font-medium">{t('style.line')}</div>
      {isDataDriven ? (
        <div className="text-xs text-muted-foreground italic">
          {layer.style_config?.target === 'width'
            ? t('style.widthByColumn', { column: layer.style_config?.column })
            : t('style.styledBy', { column: layer.style_config?.column })}
        </div>
      ) : (
        <LineGradientControls
          paint={paint}
          styleConfig={styleConfig}
          onPaintProp={onPaintProp}
          onBuilderChange={onBuilderChange}
          t={t}
        />
      )}
      <ZoomExpressionEditor
        label={t('style.opacity')}
        value={getEditableNumericPaintValue(paint, 'line-opacity', 1)}
        defaultValue={1}
        min={0} max={1} step={0.01} format="percent"
        onChange={(val) => onPaintProp('line-opacity', val)}
      />
      {!isWidthDataDriven && (
        <ZoomExpressionEditor
          label={t('style.width')}
          value={getEditableNumericPaintValue(paint, 'line-width', LINE_DEFAULTS['line-width'])}
          defaultValue={LINE_DEFAULTS['line-width']}
          min={0.5} max={20} step={0.25} format="px"
          onChange={(val) => onPaintProp('line-width', val)}
        />
      )}
      <SliderRow
        label={t('style.gapWidth')} value={getPaintValue(paint, 'line-gap-width', 0)}
        min={0} max={20} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-gap-width', val)}
      />
      <SliderRow
        label={t('style.blur')} value={getPaintValue(paint, 'line-blur', 0)}
        min={0} max={10} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-blur', val)}
      />
      <SliderRow
        label={t('style.offset')} value={getPaintValue(paint, 'line-offset', 0)}
        min={-20} max={20} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-offset', val)}
      />
      {isArrow && (
        <div className="space-y-2 rounded-md border border-border/70 bg-muted/20 p-2">
          <div className="text-xs font-medium">{t('style.arrow.title')}</div>
          <StyleColorPicker
            label={t('style.arrow.color')}
            color={arrowColor}
            onChange={(hex) => onBuilderChange({ arrowColor: hex } as BuilderStyleConfig)}
          />
          <SliderRow
            label={t('style.arrow.size')}
            value={(builder as BuilderStyleConfig).arrowSize ?? 14}
            min={8} max={28} step={1} format="px"
            onChange={(val) => onBuilderChange({ arrowSize: val } as BuilderStyleConfig)}
          />
          <SliderRow
            label={t('style.arrow.spacing')}
            value={(builder as BuilderStyleConfig).arrowSpacing ?? 80}
            min={24} max={240} step={4} format="px"
            onChange={(val) => onBuilderChange({ arrowSpacing: val } as BuilderStyleConfig)}
          />
        </div>
      )}
      <div className="text-xs font-medium mt-2">{t('style.pattern')}</div>
      <div className="flex gap-1">
        {LINE_DASH_PRESETS.map((preset, idx) => {
          const currentDashValue = paint['line-dasharray'] ?? (layer.layout as Record<string, unknown>)?.['line-dasharray'];
          const activeIdx = LINE_DASH_SERIALIZED.findIndex((s) => s === JSON.stringify(currentDashValue));
          const isActive = (activeIdx === -1 ? 0 : activeIdx) === idx;
          return (
            <button
              key={preset.key} type="button"
              className={cn(
                'flex-1 cursor-pointer px-2 py-1 text-xs rounded border transition-colors',
                isActive ? 'bg-primary text-primary-foreground border-primary' : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
              )}
              onClick={() => {
                const nextPaint = { ...paint };
                if (preset.value) {
                  nextPaint['line-dasharray'] = preset.value;
                } else {
                  delete nextPaint['line-dasharray'];
                }
                const nextLayout = { ...(layer.layout ?? {}) } as Record<string, unknown>;
                const hadLegacyLayoutDash = Object.prototype.hasOwnProperty.call(nextLayout, 'line-dasharray');
                delete nextLayout['line-dasharray'];
                onPaintChange(layer.id, nextPaint);
                if (hadLegacyLayoutDash) onLayoutChange(layer.id, nextLayout);
              }}
            >
              {t(`style.dash.${preset.key}`)}
            </button>
          );
        })}
      </div>
      <div className="text-xs font-medium mt-2">{t('style.lineEnds', { defaultValue: 'Line ends' })}</div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{t('style.lineCap', { defaultValue: 'Cap' })}</span>
        <Select
          value={((layer.layout as Record<string, unknown>)?.['line-cap'] as string) ?? 'round'}
          onValueChange={(val) => onLayoutChange(layer.id, { ...(layer.layout ?? {}), 'line-cap': val } as Record<string, unknown>)}
        >
          <SelectTrigger className="h-8 text-xs w-36" aria-label={t('style.lineCap', { defaultValue: 'Cap' })}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="butt">{t('style.lineCapButt', { defaultValue: 'Butt' })}</SelectItem>
            <SelectItem value="round">{t('style.lineCapRound', { defaultValue: 'Round' })}</SelectItem>
            <SelectItem value="square">{t('style.lineCapSquare', { defaultValue: 'Square' })}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{t('style.lineJoin', { defaultValue: 'Join' })}</span>
        <Select
          value={((layer.layout as Record<string, unknown>)?.['line-join'] as string) ?? 'round'}
          onValueChange={(val) => onLayoutChange(layer.id, { ...(layer.layout ?? {}), 'line-join': val } as Record<string, unknown>)}
        >
          <SelectTrigger className="h-8 text-xs w-36" aria-label={t('style.lineJoin', { defaultValue: 'Join' })}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="bevel">{t('style.lineJoinBevel', { defaultValue: 'Bevel' })}</SelectItem>
            <SelectItem value="round">{t('style.lineJoinRound', { defaultValue: 'Round' })}</SelectItem>
            <SelectItem value="miter">{t('style.lineJoinMiter', { defaultValue: 'Miter' })}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </>
  );
}

export default LineEditor;
