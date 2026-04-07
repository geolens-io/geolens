import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StyleColorPicker } from './StyleColorPicker';
import { DataDrivenStyleEditor } from './DataDrivenStyleEditor';
import { HeatmapStyleControls, SliderRow } from './HeatmapStyleControls';
import { getLayerType } from '@/components/builder/map-sync';
import { MAP_COLORS } from '@/lib/map-colors';
import { cn } from '@/lib/utils';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: 'points' | 'heatmap') => void;
  showAdvanced?: boolean;
}

const LINE_DASH_PRESETS = [
  { key: 'solid', value: undefined },
  { key: 'dashed', value: [4, 2] },
  { key: 'dotted', value: [1, 2] },
  { key: 'dashDot', value: [4, 2, 1, 2] },
] as const;

// Defaults per geometry type
const FILL_DEFAULTS = {
  'fill-color': MAP_COLORS.default.fill,
  'fill-opacity': MAP_COLORS.default.fillOpacity,
  '_outline-color': MAP_COLORS.default.stroke,
  '_outline-width': 1,
};

const LINE_DEFAULTS = {
  'line-color': MAP_COLORS.default.fill,
  'line-width': 2,
};

const CIRCLE_DEFAULTS = {
  'circle-color': MAP_COLORS.default.fill,
  'circle-radius': 5,
  'circle-stroke-color': MAP_COLORS.default.stroke,
  'circle-stroke-width': 1,
};

function getPaintValue<T>(paint: Record<string, unknown>, key: string, fallback: T): T {
  const val = paint[key];
  // Expression arrays (data-driven styles) aren't valid for scalar controls
  if (Array.isArray(val)) return fallback;
  return val !== undefined && val !== null ? (val as T) : fallback;
}

export function LayerStyleEditor({
  layer,
  onPaintChange,
  onOpacityChange,
  onStyleConfigChange,
  onLayoutChange,
  onRenderModeChange,
  showAdvanced,
}: LayerStyleEditorProps) {
  const { t } = useTranslation('builder');
  const geomType = getLayerType(layer.dataset_geometry_type);
  const paint = layer.paint;
  const layoutObj = (layer.layout as Record<string, unknown>) ?? {};
  const isDataDriven = !!layer.style_config?.column;
  const renderMode = ((layer.style_config as Record<string, unknown> | undefined)?.render_mode as string) || 'points';

  const fillEnabled = !paint['_fill-disabled'];
  const strokeEnabled = !paint['_stroke-disabled'];

  function handlePaintProp(key: string, value: unknown) {
    onPaintChange(layer.id, { ...paint, [key]: value });
  }

  function handleToggleFill() {
    const next = { ...paint };
    if (fillEnabled) {
      next['_fill-opacity-saved'] = getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = 0;
      next['_fill-disabled'] = true;
    } else {
      const saved = getPaintValue(paint, '_fill-opacity-saved', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = saved;
      delete next['_fill-disabled'];
      delete next['_fill-opacity-saved'];
    }
    onPaintChange(layer.id, next);
  }

  function handleToggleStroke() {
    const next = { ...paint };
    const widthKey = geomType === 'circle' ? 'circle-stroke-width' : '_outline-width';
    const defaultWidth = geomType === 'circle' ? CIRCLE_DEFAULTS['circle-stroke-width'] : FILL_DEFAULTS['_outline-width'];
    if (strokeEnabled) {
      next['_outline-width-saved'] = getPaintValue(paint, widthKey, defaultWidth);
      next[widthKey] = 0;
      next['_stroke-disabled'] = true;
    } else {
      next[widthKey] = getPaintValue(paint, '_outline-width-saved', defaultWidth);
      delete next['_stroke-disabled'];
      delete next['_outline-width-saved'];
    }
    onPaintChange(layer.id, next);
  }

  return (
    <div className="space-y-3">
      {/* Render as dropdown — point layers only */}
      {geomType === 'circle' && (
        <div className="space-y-1">
          <div className="text-xs font-medium">{t('style.renderAs')}</div>
          <Select
            value={renderMode}
            onValueChange={(mode) => onRenderModeChange?.(layer.id, mode as 'points' | 'heatmap')}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="points">{t('style.renderPoints')}</SelectItem>
              <SelectItem value="heatmap">{t('style.renderHeatmap')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Heatmap controls — shown when render mode is heatmap */}
      {geomType === 'circle' && renderMode === 'heatmap' && (
        <HeatmapStyleControls layer={layer} onPaintChange={onPaintChange} />
      )}

      {/* Data-driven style editor — hidden when in heatmap mode */}
      {renderMode !== 'heatmap' && (
        <DataDrivenStyleEditor
          layer={layer}
          onStyleConfigChange={onStyleConfigChange}
        />
      )}

      {/* Flat color controls */}
      <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
        {/* Polygon (fill) controls */}
        {geomType === 'fill' && (
          <>
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium">{t('style.fill')}</div>
              <Switch
                checked={fillEnabled}
                onCheckedChange={handleToggleFill}
                aria-label={t('style.toggleFill')}
                className="scale-75"
              />
            </div>
            {fillEnabled && (
              <>
                {isDataDriven ? (
                  <div className="text-xs text-muted-foreground italic">
                    {t('style.styledBy', { column: layer.style_config!.column })}
                  </div>
                ) : (
                  <StyleColorPicker
                    label={t('style.color')}
                    color={getPaintValue(paint, 'fill-color', FILL_DEFAULTS['fill-color'])}
                    onChange={(hex) => handlePaintProp('fill-color', hex)}
                  />
                )}
                <SliderRow
                  label={t('style.opacity')}
                  value={getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity'])}
                  min={0}
                  max={1}
                  step={0.01}
                  format="percent"
                  onChange={(val) => handlePaintProp('fill-opacity', val)}
                />
              </>
            )}
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
              <Switch
                checked={strokeEnabled}
                onCheckedChange={handleToggleStroke}
                aria-label={t('style.toggleStroke')}
                className="scale-75 mt-2"
              />
            </div>
            {strokeEnabled && (
              <>
                <StyleColorPicker
                  label={t('style.color')}
                  color={getPaintValue(paint, '_outline-color', FILL_DEFAULTS['_outline-color'])}
                  onChange={(hex) => handlePaintProp('_outline-color', hex)}
                />
                <SliderRow
                  label={t('style.width')}
                  value={getPaintValue(paint, '_outline-width', FILL_DEFAULTS['_outline-width'])}
                  min={0}
                  max={10}
                  step={0.5}
                  format="px"
                  onChange={(val) => handlePaintProp('_outline-width', val)}
                />
              </>
            )}
          </>
        )}

        {/* Line controls */}
        {geomType === 'line' && (
          <>
            <div className="text-xs font-medium">{t('style.line')}</div>
            {isDataDriven ? (
              <div className="text-xs text-muted-foreground italic">
                {layer.style_config!.target === 'width'
                  ? t('style.widthByColumn', { column: layer.style_config!.column })
                  : t('style.styledBy', { column: layer.style_config!.column })}
              </div>
            ) : (
              <StyleColorPicker
                label={t('style.color')}
                color={getPaintValue(paint, 'line-color', LINE_DEFAULTS['line-color'])}
                onChange={(hex) => handlePaintProp('line-color', hex)}
              />
            )}
            <SliderRow
              label={t('style.opacity')}
              value={getPaintValue(paint, 'line-opacity', 1)}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={(val) => handlePaintProp('line-opacity', val)}
            />
            <SliderRow
              label={t('style.width')}
              value={getPaintValue(paint, 'line-width', LINE_DEFAULTS['line-width'])}
              min={1}
              max={20}
              step={0.5}
              format="px"
              onChange={(val) => handlePaintProp('line-width', val)}
            />
            <div className="text-xs font-medium mt-2">{t('style.pattern')}</div>
            <div className="flex gap-1">
              {LINE_DASH_PRESETS.map((preset) => {
                const currentDashValue = (layer.layout as Record<string, unknown>)?.['line-dasharray'];
                const isActive = (LINE_DASH_PRESETS.find(
                  (p) => JSON.stringify(p.value) === JSON.stringify(currentDashValue),
                )?.key ?? 'solid') === preset.key;
                return (
                  <button
                    key={preset.key}
                    type="button"
                    className={cn(
                      'flex-1 px-2 py-1 text-xs rounded border transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
                    )}
                    onClick={() => {
                      const newLayout = { ...(layer.layout ?? {}), 'line-dasharray': preset.value } as Record<string, unknown>;
                      if (!preset.value) delete newLayout['line-dasharray'];
                      onLayoutChange(layer.id, newLayout);
                    }}
                  >
                    {t(`style.dash.${preset.key}`)}
                  </button>
                );
              })}
            </div>
          </>
        )}

        {/* Circle (point) controls — hidden when in heatmap mode */}
        {geomType === 'circle' && renderMode !== 'heatmap' && (
          <>
            <div className="text-xs font-medium">{t('style.point')}</div>
            {isDataDriven ? (
              <div className="text-xs text-muted-foreground italic">
                {layer.style_config!.target === 'radius'
                  ? t('style.radiusByColumn', { column: layer.style_config!.column })
                  : t('style.styledBy', { column: layer.style_config!.column })}
              </div>
            ) : (
              <StyleColorPicker
                label={t('style.color')}
                color={getPaintValue(paint, 'circle-color', CIRCLE_DEFAULTS['circle-color'])}
                onChange={(hex) => handlePaintProp('circle-color', hex)}
              />
            )}
            <SliderRow
              label={t('style.opacity')}
              value={getPaintValue(paint, 'circle-opacity', 1)}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={(val) => handlePaintProp('circle-opacity', val)}
            />
            <SliderRow
              label={t('style.radius')}
              value={getPaintValue(paint, 'circle-radius', CIRCLE_DEFAULTS['circle-radius'])}
              min={1}
              max={30}
              step={1}
              format="px"
              onChange={(val) => handlePaintProp('circle-radius', val)}
            />
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
              <Switch
                checked={strokeEnabled}
                onCheckedChange={handleToggleStroke}
                aria-label={t('style.toggleStroke')}
                className="scale-75 mt-2"
              />
            </div>
            {strokeEnabled && (
              <>
                <StyleColorPicker
                  label={t('style.color')}
                  color={getPaintValue(paint, 'circle-stroke-color', CIRCLE_DEFAULTS['circle-stroke-color'])}
                  onChange={(hex) => handlePaintProp('circle-stroke-color', hex)}
                />
                <SliderRow
                  label={t('style.width')}
                  value={getPaintValue(paint, 'circle-stroke-width', CIRCLE_DEFAULTS['circle-stroke-width'])}
                  min={0}
                  max={10}
                  step={0.5}
                  format="px"
                  onChange={(val) => handlePaintProp('circle-stroke-width', val)}
                />
              </>
            )}
          </>
        )}

        {/* Master opacity - all geometry types */}
        <div className="text-xs font-medium mt-2 pt-2 border-t">{t('style.opacity')}</div>
        <SliderRow
          label={t('style.layer')}
          value={layer.opacity}
          min={0}
          max={1}
          step={0.01}
          format="percent"
          onChange={(val) => onOpacityChange(layer.id, val)}
        />

        {/* Layer zoom range */}
        <div className="text-xs font-medium mt-2 pt-2 border-t">{t('style.zoomRange')}</div>
        <SliderRow
          label={t('style.minZoom')}
          value={layoutObj['_minzoom'] as number ?? 0}
          min={0}
          max={(layoutObj['_maxzoom'] as number ?? 22) - 1}
          step={1}
          format="zoom"
          onChange={(val) => onLayoutChange(layer.id, { ...layoutObj, '_minzoom': val })}
        />
        <SliderRow
          label={t('style.maxZoom')}
          value={layoutObj['_maxzoom'] as number ?? 22}
          min={(layoutObj['_minzoom'] as number ?? 0) + 1}
          max={22}
          step={1}
          format="zoom"
          onChange={(val) => onLayoutChange(layer.id, { ...layoutObj, '_maxzoom': val })}
        />
      </div>

      {/* Advanced JSON editor — hidden when showAdvanced is explicitly false */}
      {showAdvanced !== false && (
        <AdvancedJsonEditor
          paint={paint}
          layout={(layer.layout as Record<string, unknown>) ?? {}}
          onPaintChange={(p) => onPaintChange(layer.id, p)}
          onLayoutChange={(l) => onLayoutChange(layer.id, l)}
          defaultOpen={showAdvanced === true}
        />
      )}
    </div>
  );
}

/* ---------- Advanced JSON editor ---------- */

interface AdvancedJsonEditorProps {
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  onPaintChange: (paint: Record<string, unknown>) => void;
  onLayoutChange: (layout: Record<string, unknown>) => void;
  defaultOpen?: boolean;
}

function AdvancedJsonEditor({ paint, layout, onPaintChange, onLayoutChange, defaultOpen = false }: AdvancedJsonEditorProps) {
  const { t } = useTranslation('builder');
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-t pt-2">
      <button
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Code className="h-3 w-3" />
        {t('style.advancedJson')}
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          <JsonBlock
            label={t('style.paintJson')}
            value={paint}
            onApply={onPaintChange}
          />
          <JsonBlock
            label={t('style.layoutJson')}
            value={layout}
            onApply={onLayoutChange}
          />
        </div>
      )}
    </div>
  );
}

function JsonBlock({ label, value, onApply }: { label: string; value: Record<string, unknown>; onApply: (v: Record<string, unknown>) => void }) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  function handleOpen() {
    setText(JSON.stringify(value, null, 2));
    setError(null);
    setEditing(true);
  }

  function handleApply() {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError(t('style.jsonError'));
        return;
      }
      onApply(parsed);
      setError(null);
      setEditing(false);
    } catch {
      setError(t('style.jsonError'));
    }
  }

  if (!editing) {
    return (
      <div>
        <button
          className="text-xs text-muted-foreground hover:text-foreground underline"
          onClick={handleOpen}
        >
          {label}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <textarea
        className="w-full rounded border border-input bg-background p-2 text-xs font-mono resize-y min-h-[80px] outline-none focus:ring-1 focus:ring-ring"
        value={text}
        onChange={(e) => { setText(e.target.value); setError(null); }}
        spellCheck={false}
      />
      {error && <div className="text-xs text-destructive">{error}</div>}
      <div className="flex gap-1.5">
        <Button size="sm" className="h-6 text-xs px-2" onClick={handleApply}>
          {t('style.jsonApply')}
        </Button>
        <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={() => setEditing(false)}>
          {t('style.jsonCancel')}
        </Button>
      </div>
    </div>
  );
}

