import { StyleColorPicker } from '../StyleColorPicker';
import { ZoomExpressionEditor } from '../ZoomExpressionEditor';
import { StrokeControls } from './StrokeControls';
import { getPaintValue, getEditableNumericPaintValue, CIRCLE_DEFAULTS } from './utils';
import type { BaseStyleEditorProps } from './types';

export function CircleEditor({
  layer,
  paint,
  isDataDriven,
  strokeEnabled,
  onToggleStroke,
  onPaintProp,
  t,
}: BaseStyleEditorProps) {
  const isRadiusDataDriven = isDataDriven && layer.style_config?.target === 'radius';

  return (
    <>
      <div className="text-xs font-medium">{t('style.point')}</div>
      {isDataDriven ? (
        <div className="text-xs text-muted-foreground italic">
          {layer.style_config?.target === 'radius'
            ? t('style.radiusByColumn', { column: layer.style_config?.column })
            : t('style.styledBy', { column: layer.style_config?.column })}
        </div>
      ) : (
        <StyleColorPicker
          label={t('style.color')}
          color={getPaintValue(paint, 'circle-color', CIRCLE_DEFAULTS['circle-color'])}
          onChange={(hex) => onPaintProp('circle-color', hex)}
        />
      )}
      <ZoomExpressionEditor
        label={t('style.opacity')}
        value={getEditableNumericPaintValue(paint, 'circle-opacity', 1)}
        defaultValue={1}
        min={0} max={1} step={0.01} format="percent"
        onChange={(val) => onPaintProp('circle-opacity', val)}
      />
      {!isRadiusDataDriven && (
        <ZoomExpressionEditor
          label={t('style.radius')}
          value={getEditableNumericPaintValue(paint, 'circle-radius', CIRCLE_DEFAULTS['circle-radius'])}
          defaultValue={CIRCLE_DEFAULTS['circle-radius']}
          min={1} max={30} step={1} format="px"
          onChange={(val) => onPaintProp('circle-radius', val)}
        />
      )}
      <StrokeControls
        paint={paint} strokeEnabled={strokeEnabled} onToggleStroke={onToggleStroke}
        colorKey="circle-stroke-color" colorDefault={CIRCLE_DEFAULTS['circle-stroke-color']}
        widthKey="circle-stroke-width" widthDefault={CIRCLE_DEFAULTS['circle-stroke-width']}
        onPaintProp={onPaintProp} t={t}
      />
    </>
  );
}

export default CircleEditor;
