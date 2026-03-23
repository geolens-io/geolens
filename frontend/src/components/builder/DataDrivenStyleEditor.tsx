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
  getColorProperty,
} from '@/lib/color-ramps';
import { equalIntervalBreaks, quantileBreaks } from '@/lib/classification';
import { MAP_COLORS } from '@/lib/map-colors';
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
const NUMERIC_TYPES = [
  'integer', 'numeric', 'real', 'double', 'float',
  'bigint', 'smallint', 'int4', 'int8', 'int2', 'float4', 'float8',
];

function isTextColumn(type: string): boolean {
  const t = type.toLowerCase();
  return TEXT_TYPES.some((tt) => t.includes(tt));
}

function isNumericColumn(type: string): boolean {
  const t = type.toLowerCase();
  return NUMERIC_TYPES.some((nt) => t.includes(nt));
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
      const colors = getRampColors(ramp, Math.max(values.length, 1));
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const valueColorMap: [string, string][] = values.map((v, i) => [v, colors[i]]);
      const expression = buildCategoricalExpression(column, valueColorMap, MAP_COLORS.fallback);

      const categories = values.map((v, i) => ({ value: v, color: colors[i] }));
      const config: StyleConfig = { mode: 'categorical', column, ramp, categories };
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
      const colors = getRampColors(ramp, effectiveClassCount);
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const expression = buildGraduatedExpression(column, breaks, colors);

      const config: StyleConfig = {
        mode: 'graduated',
        column,
        ramp,
        classCount: effectiveClassCount,
        method,
        breaks,
        colors,
      };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, config, paint);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [column, mode, ramp, classCount, method, valuesData, statsData]);

  function handleClear() {
    setColumn('');
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const resetPaint = { ...layer.paint, [colorProp]: MAP_COLORS.default.fill };
    onStyleConfigChange(layer.id, null, resetPaint);
  }

  function handleModeChange(newMode: 'categorical' | 'graduated') {
    setMode(newMode);
    setColumn('');
    setRamp(newMode === 'categorical' ? 'Set2' : 'YlOrRd');
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
      const newConfig: StyleConfig = { ...config, categories: updated };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, newConfig, paint);
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
      const newConfig: StyleConfig = { ...config, colors: updatedColors };
      const paint = { ...layer.paint, [colorProp]: expression };
      onStyleConfigChange(layer.id, newConfig, paint);
    },
    [layer, onStyleConfigChange],
  );

  const hasTooManyCategories =
    mode === 'categorical' && valuesData && valuesData.values.length > 20;

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

      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-20">{t('dataDriven.column')}</span>
        <Select value={column} onValueChange={setColumn}>
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

      {column && (
        <>
          <div className="text-xs text-muted-foreground">{t('dataDriven.colorRamp')}</div>
          <ColorRampPicker rampName={ramp} onChange={setRamp} mode={mode} />
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
                      className="mt-2 w-full text-xs border rounded px-2 py-1"
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

      {/* Per-class color editing for graduated */}
      {column && mode === 'graduated' && layer.style_config?.colors && layer.style_config?.breaks && (
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
                        className="mt-2 w-full text-xs border rounded px-2 py-1"
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
              <span className="text-xs text-muted-foreground w-10 text-right">
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
