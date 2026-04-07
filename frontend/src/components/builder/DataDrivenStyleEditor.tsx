import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { HexColorPicker, HexColorInput } from 'react-colorful';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { ColorRampPicker } from './ColorRampPicker';
import { useColumnValues, useColumnStats } from '@/hooks/use-maps';
import {
  getRampColors,
  buildCategoricalExpression,
  buildGraduatedExpression,
  buildGraduatedSizeExpression,
  getColorProperty,
  getSizeProperty,
} from '@/lib/color-ramps';
import { getLayerType } from '@/components/builder/map-sync';
import { equalIntervalBreaks, quantileBreaks } from '@/lib/classification';
import { MAP_COLORS } from '@/lib/map-colors';
import { isNumericColumn } from '@/lib/column-utils';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

interface DataDrivenStyleEditorProps {
  layer: MapLayerResponse;
  onStyleConfigChange: (
    layerId: string,
    config: StyleConfig | null,
    paint: Record<string, unknown>,
  ) => void;
}

const TEXT_TYPES = ['character', 'text', 'varchar', 'char'];

function isTextColumn(type: string): boolean {
  const t = type.toLowerCase();
  return TEXT_TYPES.some((tt) => t.includes(tt));
}

/** Linearly interpolate classCount values between sizeRange[0] and sizeRange[1]. */
function computeSizes(sizeRange: [number, number], classCount: number): number[] {
  if (classCount < 2) return [sizeRange[0]];
  const sizes: number[] = [];
  for (let i = 0; i < classCount; i++) {
    const t = i / (classCount - 1);
    sizes.push(Math.round((sizeRange[0] + t * (sizeRange[1] - sizeRange[0])) * 10) / 10);
  }
  return sizes;
}

function defaultSizeRange(tgt: 'color' | 'radius' | 'width'): [number, number] {
  if (tgt === 'width') return [1, 10];
  return [2, 20]; // radius default
}

export function DataDrivenStyleEditor({
  layer,
  onStyleConfigChange,
}: DataDrivenStyleEditorProps) {
  const { t } = useTranslation('builder');
  const existingConfig = layer.style_config;

  const [mode, setMode] = useState<'categorical' | 'graduated'>(
    existingConfig?.mode ?? 'categorical',
  );
  const [column, setColumn] = useState<string>(existingConfig?.column ?? '');
  const [ramp, setRamp] = useState<string>(existingConfig?.ramp ?? 'Set2');
  const [classCount, setClassCount] = useState<number>(
    existingConfig?.classCount ?? 5,
  );
  const [method, setMethod] = useState<'equal_interval' | 'quantile'>(
    existingConfig?.method ?? 'equal_interval',
  );
  const [target, setTarget] = useState<'color' | 'radius' | 'width'>(
    existingConfig?.target ?? 'color',
  );
  const [sizeRange, setSizeRange] = useState<[number, number]>(
    existingConfig?.sizeRange ?? defaultSizeRange(existingConfig?.target ?? 'color'),
  );

  // Determine available targets for this layer's geometry type
  const layerType = getLayerType(layer.dataset_geometry_type);
  const availableTargets: ('color' | 'radius' | 'width')[] =
    layerType === 'circle'
      ? ['color', 'radius']
      : layerType === 'line'
        ? ['color', 'width']
        : ['color'];

  const columns = layer.dataset_column_info ?? [];
  const textColumns = columns.filter((c) => isTextColumn(c.type));
  const numericColumns = columns.filter((c) => isNumericColumn(c.type));
  const filteredColumns = mode === 'categorical' ? textColumns : numericColumns;

  const columnForCategorical = mode === 'categorical' && column ? column : undefined;
  const columnForGraduated = mode === 'graduated' && column ? column : undefined;

  const { data: valuesData } = useColumnValues(
    columnForCategorical ? layer.dataset_id : undefined,
    columnForCategorical,
  );
  const { data: statsData } = useColumnStats(
    columnForGraduated ? layer.dataset_id : undefined,
    columnForGraduated,
  );

  useEffect(() => {
    if (!column) return;

    if (mode === 'categorical' && valuesData) {
      const values = valuesData.values;
      const colorProp = getColorProperty(layer.dataset_geometry_type);

      // Preserve existing per-category colors when column and ramp haven't changed
      const ec = layer.style_config;
      if (
        ec?.mode === 'categorical' &&
        ec.column === column &&
        ec.ramp === ramp &&
        ec.categories &&
        ec.categories.length === values.length &&
        ec.categories.every((c, i) => c.value === values[i])
      ) {
        return;
      }

      // Resolve 'custom' to a real ramp when regenerating (e.g., column change)
      const effectiveRamp = ramp === 'custom' ? 'Set2' : ramp;
      if (ramp === 'custom') setRamp(effectiveRamp);

      const colors = getRampColors(effectiveRamp, Math.max(values.length, 1));
      const valueColorMap: [string, string][] = values.map((v, i) => [v, colors[i]]);
      const expression = buildCategoricalExpression(column, valueColorMap, MAP_COLORS.fallback);

      const categories = values.map((v, i) => ({ value: v, color: colors[i] }));
      const config: StyleConfig = { mode: 'categorical', column, ramp: effectiveRamp, categories };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, config, paint);
    }

    if (mode === 'graduated' && statsData && statsData.min !== null && statsData.max !== null) {
      let breaks: number[];
      if (method === 'quantile' && statsData.quantiles.length > 0) {
        breaks = quantileBreaks(statsData.quantiles);
      } else {
        breaks = equalIntervalBreaks(statsData.min, statsData.max, classCount);
      }

      const effectiveClassCount = method === 'quantile' ? breaks.length + 1 : classCount;

      if (target === 'color' || !target) {
        // Preserve existing graduated colors when config hasn't changed
        const ec = layer.style_config;
        if (
          ec?.mode === 'graduated' &&
          ec.column === column &&
          ec.ramp === ramp &&
          ec.method === method &&
          ec.classCount === classCount &&
          ec.colors &&
          ec.breaks &&
          (!ec.target || ec.target === 'color')
        ) {
          return;
        }

        // Resolve 'custom' to a real ramp when regenerating (e.g., column change)
        const effectiveRamp = ramp === 'custom' ? 'YlOrRd' : ramp;
        if (ramp === 'custom') setRamp(effectiveRamp);

        const colors = getRampColors(effectiveRamp, effectiveClassCount);
        const colorProp = getColorProperty(layer.dataset_geometry_type);
        const expression = buildGraduatedExpression(column, breaks, colors);

        const config: StyleConfig = {
          mode: 'graduated',
          column,
          ramp: effectiveRamp,
          classCount: effectiveClassCount,
          method,
          breaks,
          colors,
          target: 'color',
        };
        const paint = { ...layer.paint, [colorProp]: expression };
        onStyleConfigChange(layer.id, config, paint);
      } else {
        // Size target (radius or width)
        const ec = layer.style_config;
        // Guard: skip if existing config already matches
        if (
          ec?.target === target &&
          ec.column === column &&
          ec.method === method &&
          ec.classCount === effectiveClassCount &&
          ec.sizes &&
          ec.sizeRange &&
          ec.sizeRange[0] === sizeRange[0] &&
          ec.sizeRange[1] === sizeRange[1]
        ) {
          return;
        }

        const sizeProp = getSizeProperty(layer.dataset_geometry_type, target);
        if (!sizeProp) return;

        const sizes = computeSizes(sizeRange, effectiveClassCount);
        const sizeExpression = buildGraduatedSizeExpression(column, breaks, sizes);

        const config: StyleConfig = {
          mode: 'graduated',
          column,
          ramp,
          classCount: effectiveClassCount,
          method,
          breaks,
          target,
          sizes,
          sizeRange,
        };
        // Keep existing color expression + add size expression
        const paint = { ...layer.paint, [sizeProp]: sizeExpression };
        onStyleConfigChange(layer.id, config, paint);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [column, mode, ramp, classCount, method, target, sizeRange, valuesData, statsData]);

  function handleClear() {
    setColumn('');
    setTarget('color');
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const resetPaint: Record<string, unknown> = {
      ...layer.paint,
      [colorProp]: MAP_COLORS.default.fill,
    };
    // Reset size paint properties to scalar defaults
    const radiusProp = getSizeProperty(layer.dataset_geometry_type, 'radius');
    if (radiusProp) resetPaint[radiusProp] = 5;
    const widthProp = getSizeProperty(layer.dataset_geometry_type, 'width');
    if (widthProp) resetPaint[widthProp] = 2;
    onStyleConfigChange(layer.id, null, resetPaint);
  }

  function handleColumnChange(newColumn: string) {
    if (!newColumn) {
      setColumn('');
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const basePaint: Record<string, unknown> = {
        ...layer.paint,
        [colorProp]: MAP_COLORS.default.fill,
      };
      onStyleConfigChange(layer.id, null, basePaint);
    } else {
      setColumn(newColumn);
    }
  }

  function handleModeChange(newMode: 'categorical' | 'graduated') {
    setMode(newMode);
    setColumn('');
    setRamp(newMode === 'categorical' ? 'Set2' : 'YlOrRd');
    if (newMode === 'categorical') {
      // Categorical does not support size targets — force back to color
      setTarget('color');
      // Reset any size paint property to scalar default
      const radiusProp = getSizeProperty(layer.dataset_geometry_type, 'radius');
      const widthProp = getSizeProperty(layer.dataset_geometry_type, 'width');
      if (radiusProp || widthProp) {
        const resetPaint: Record<string, unknown> = { ...layer.paint };
        if (radiusProp) resetPaint[radiusProp] = 5;
        if (widthProp) resetPaint[widthProp] = 2;
        onStyleConfigChange(layer.id, layer.style_config ?? null, resetPaint);
      }
    }
  }

  function handleTargetChange(newTarget: 'color' | 'radius' | 'width') {
    setTarget(newTarget);
    setSizeRange(defaultSizeRange(newTarget));
  }

  const handleCategoryColorChange = useCallback(
    (value: string, newColor: string) => {
      const config = layer.style_config;
      if (!config?.categories) return;

      const updated = config.categories.map((c) =>
        c.value === value ? { ...c, color: newColor } : c,
      );
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const valueColorMap: [string, string][] = updated.map((c) => [c.value, c.color]);
      const expression = buildCategoricalExpression(
        config.column,
        valueColorMap,
        MAP_COLORS.fallback,
      );
      const newConfig: StyleConfig = { ...config, categories: updated, ramp: 'custom' };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, newConfig, paint);
      setRamp('custom');
    },
    [layer, onStyleConfigChange],
  );

  const handleGraduatedColorChange = useCallback(
    (index: number, newColor: string) => {
      const config = layer.style_config;
      if (!config?.colors || !config.breaks) return;

      const updatedColors = [...config.colors];
      updatedColors[index] = newColor;
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const expression = buildGraduatedExpression(config.column, config.breaks, updatedColors);
      const newConfig: StyleConfig = { ...config, colors: updatedColors, ramp: 'custom' };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, newConfig, paint);
      setRamp('custom');
    },
    [layer, onStyleConfigChange],
  );

  const hasTooManyCategories =
    mode === 'categorical' && valuesData && valuesData.values.length > 20;

  const showTargetSelector = availableTargets.length > 1 && mode === 'graduated';
  const isSizeTarget = target !== 'color' && mode === 'graduated';

  return (
    <div className="space-y-2.5 p-3 bg-muted/30 rounded-md border">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">{t('dataDriven.title')}</Label>
        {column && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={handleClear}
            title={t('dataDriven.clearTitle')}
            aria-label={t('dataDriven.clearTitle')}
          >
            <X className="h-3 w-3" />
          </Button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-20">{t('dataDriven.mode')}</span>
        <Select value={mode} onValueChange={(v) => handleModeChange(v as 'categorical' | 'graduated')}>
          <SelectTrigger className="h-7 text-xs flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="categorical" className="text-xs">
              {t('dataDriven.categorical')}
            </SelectItem>
            <SelectItem value="graduated" className="text-xs">
              {t('dataDriven.graduated')}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Target selector — only for point and line layers in graduated mode */}
      {showTargetSelector && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-20">{t('dataDriven.target')}</span>
          <Select
            value={target}
            onValueChange={(v) => handleTargetChange(v as 'color' | 'radius' | 'width')}
          >
            <SelectTrigger className="h-7 text-xs flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {availableTargets.map((tgt) => (
                <SelectItem key={tgt} value={tgt} className="text-xs">
                  {tgt === 'color'
                    ? t('dataDriven.targetColor')
                    : tgt === 'radius'
                      ? t('dataDriven.targetRadius')
                      : t('dataDriven.targetWidth')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-20">{t('dataDriven.column')}</span>
        <Select value={column} onValueChange={handleColumnChange}>
          <SelectTrigger className="h-7 text-xs flex-1">
            <SelectValue placeholder={t('dataDriven.selectColumn')} />
          </SelectTrigger>
          <SelectContent>
            {filteredColumns.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">
                {mode === 'categorical' ? t('dataDriven.noTextColumns') : t('dataDriven.noNumericColumns')}
              </div>
            ) : (
              filteredColumns.map((col) => (
                <SelectItem key={col.name} value={col.name} className="text-xs">
                  {col.name}
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      </div>

      {/* Color ramp — only shown for color target */}
      {column && !isSizeTarget && (
        <>
          <div className="text-xs text-muted-foreground">{t('dataDriven.colorRamp')}</div>
          <ColorRampPicker
            rampName={ramp}
            onChange={setRamp}
            mode={mode}
            customColors={ramp === 'custom' && layer.style_config?.colors ? layer.style_config.colors : undefined}
          />
        </>
      )}

      {/* Size range controls — shown when target is radius or width */}
      {column && isSizeTarget && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('dataDriven.sizeMin')}</span>
            <Slider
              value={[sizeRange[0]]}
              min={1}
              max={target === 'width' ? 20 : 30}
              step={target === 'width' ? 0.5 : 1}
              onValueChange={([v]) => setSizeRange([v, Math.max(v, sizeRange[1])])}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-end">{sizeRange[0]}px</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('dataDriven.sizeMax')}</span>
            <Slider
              value={[sizeRange[1]]}
              min={1}
              max={target === 'width' ? 20 : 30}
              step={target === 'width' ? 0.5 : 1}
              onValueChange={([v]) => setSizeRange([Math.min(sizeRange[0], v), v])}
              className="flex-1"
            />
            <span className="text-xs text-muted-foreground w-10 text-end">{sizeRange[1]}px</span>
          </div>
        </>
      )}

      {/* Per-category color editing */}
      {column && mode === 'categorical' && layer.style_config?.categories && (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">{t('dataDriven.colors')}</div>
          <div className="max-h-36 overflow-y-auto space-y-0.5">
            {layer.style_config.categories.map((cat) => (
              <div key={cat.value} className="flex items-center gap-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <button
                      className="w-5 h-5 rounded-sm border border-border shrink-0 cursor-pointer hover:ring-2 hover:ring-primary/30 transition-shadow"
                      style={{ background: cat.color }}
                      title={cat.color}
                    />
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-3" align="start" side="right">
                    <HexColorPicker
                      color={cat.color}
                      onChange={(hex) => handleCategoryColorChange(cat.value, hex)}
                    />
                    <HexColorInput
                      color={cat.color}
                      onChange={(hex) => {
                        if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
                          handleCategoryColorChange(cat.value, hex);
                        }
                      }}
                      className="mt-2 w-full text-xs border rounded px-2 py-1 bg-background text-foreground"
                      prefixed
                    />
                  </PopoverContent>
                </Popover>
                <span className="text-xs truncate">{cat.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-class color editing for graduated color mode */}
      {column && mode === 'graduated' && !isSizeTarget && layer.style_config?.colors && layer.style_config?.breaks && (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">{t('dataDriven.colors')}</div>
          <div className="max-h-36 overflow-y-auto space-y-0.5">
            {layer.style_config.colors.map((color, i) => {
              const breaks = layer.style_config!.breaks!;
              const label =
                i === 0
                  ? `< ${breaks[0]}`
                  : i === breaks.length
                    ? `≥ ${breaks[breaks.length - 1]}`
                    : `${breaks[i - 1]} – ${breaks[i]}`;
              return (
                <div key={i} className="flex items-center gap-2">
                  <Popover>
                    <PopoverTrigger asChild>
                      <button
                        className="w-5 h-5 rounded-sm border border-border shrink-0 cursor-pointer hover:ring-2 hover:ring-primary/30 transition-shadow"
                        style={{ background: color }}
                        title={color}
                      />
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-3" align="start" side="right">
                      <HexColorPicker
                        color={color}
                        onChange={(hex) => handleGraduatedColorChange(i, hex)}
                      />
                      <HexColorInput
                        color={color}
                        onChange={(hex) => {
                          if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
                            handleGraduatedColorChange(i, hex);
                          }
                        }}
                        className="mt-2 w-full text-xs border rounded px-2 py-1 bg-background text-foreground"
                        prefixed
                      />
                    </PopoverContent>
                  </Popover>
                  <span className="text-xs text-muted-foreground truncate">{label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {column && mode === 'graduated' && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-20">{t('dataDriven.method')}</span>
            <Select value={method} onValueChange={(v) => setMethod(v as 'equal_interval' | 'quantile')}>
              <SelectTrigger className="h-7 text-xs flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="equal_interval" className="text-xs">
                  {t('dataDriven.equalInterval')}
                </SelectItem>
                <SelectItem value="quantile" className="text-xs">
                  {t('dataDriven.quantile')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {method === 'equal_interval' && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-20">{t('dataDriven.classes')}</span>
              <Slider
                value={[classCount]}
                min={3}
                max={9}
                step={1}
                onValueChange={([v]) => setClassCount(v)}
                className="flex-1"
              />
              <span className="text-xs text-muted-foreground w-10 text-end">
                {classCount}
              </span>
            </div>
          )}
        </>
      )}

      {hasTooManyCategories && (
        <p className="text-[10px] text-warning">
          {t('dataDriven.categoriesWarning', { count: valuesData.values.length })}
        </p>
      )}
    </div>
  );
}
