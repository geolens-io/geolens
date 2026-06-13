import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
  reverseRamp,
  buildCategoricalExpression,
  buildGraduatedExpression,
  buildGraduatedSizeExpression,
  getColorProperty,
  getSizeProperty,
  nextRotatingRamp,
  suggestRampForMode,
} from '@/lib/color-ramps';
import { getLayerType } from '@/components/builder/map-sync';
import {
  equalIntervalBreaks,
  quantileBreaks,
  jenksBreaks,
  stdDevBreaks,
  manualBreaks,
} from '@/lib/classification';
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
  /**
   * ENH-08: Zero-based ordinal of this layer within the map's data-driven
   * layer set.  Used to rotate the default palette so successive freshly-added
   * layers don't collide on the same colors.  Defaults to 0 when omitted.
   * Only affects FRESH layers (no existingConfig.ramp); saved layers keep
   * their persisted ramp regardless of this value.
   */
  rampRotationIndex?: number;
}

const TEXT_TYPES = ['character', 'text', 'varchar', 'char'];

function isTextColumn(type: string): boolean {
  const t = type.toLowerCase();
  return TEXT_TYPES.some((tt) => t.includes(tt));
}

type ClassificationMethod =
  | 'quantile'
  | 'equal_interval'
  | 'jenks'
  | 'std_dev'
  | 'manual';

/**
 * KISS-N2: compute classification breaks + effective class count, shared
 * between the graduated-color and graduated-size effects.
 * - quantile method: uses precomputed quantiles when available (actual class
 *   count becomes breaks.length + 1 because each break separates two classes)
 * - equal-interval: respects the requested classCount exactly
 * - jenks: natural-breaks over the SAMPLE (server quantiles) — the raw column
 *   is not client-side available, so this is honestly sampled, not exact.
 * - std_dev: mean ± σ steps; only valid when stddev is available (gated in UI).
 * - manual: user-supplied ascending breaks; invalid input yields the previous
 *   valid set with `invalid: true` so the caller can warn instead of writing a
 *   broken step expression.
 */
function computeBreaks(
  statsData: {
    min: number;
    max: number;
    quantiles: number[];
    mean?: number | null;
    stddev?: number | null;
  },
  method: ClassificationMethod,
  classCount: number,
  manualBreakValues: number[] = [],
): { breaks: number[]; effectiveClassCount: number; invalid: boolean } {
  let breaks: number[];
  let invalid = false;
  if (method === 'quantile' && statsData.quantiles.length > 0) {
    breaks = quantileBreaks(statsData.quantiles);
  } else if (method === 'jenks') {
    // The raw column array is not client-available; classify the representative
    // sample (server quantiles + min/max anchors), labelled "(sampled)" in UI.
    const sample = [statsData.min, ...statsData.quantiles, statsData.max];
    breaks = jenksBreaks(sample, classCount);
  } else if (method === 'std_dev') {
    if (statsData.mean != null && statsData.stddev != null) {
      breaks = stdDevBreaks(statsData.mean, statsData.stddev, classCount);
    } else {
      // Should be gated in UI; fall back rather than fabricate σ.
      breaks = equalIntervalBreaks(statsData.min, statsData.max, classCount);
    }
  } else if (method === 'manual') {
    try {
      breaks = manualBreaks(manualBreakValues);
      if (breaks.length === 0) invalid = true;
    } catch {
      breaks = [];
      invalid = true;
    }
  } else {
    breaks = equalIntervalBreaks(statsData.min, statsData.max, classCount);
  }
  // Deduplicate: MapLibre step expressions require strictly ascending breaks.
  // Quantile methods can produce duplicate boundaries when data is heavily clustered.
  breaks = [...new Set(breaks)];
  const effectiveClassCount = breaks.length + 1;
  return { breaks, effectiveClassCount, invalid };
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
  rampRotationIndex = 0,
}: DataDrivenStyleEditorProps) {
  const { t } = useTranslation('builder');
  const existingConfig = layer.style_config;

  const [mode, setMode] = useState<'categorical' | 'graduated'>(
    existingConfig?.mode ?? 'categorical',
  );
  const [column, setColumn] = useState<string>(existingConfig?.column ?? '');
  // ENH-08: For fresh layers (no saved ramp) seed the default via rotating
  // palette selection so successive adds don't all start with the same color.
  // Saved layers always keep their persisted ramp.
  const [ramp, setRamp] = useState<string>(
    existingConfig?.ramp ?? nextRotatingRamp(existingConfig?.mode ?? 'categorical', rampRotationIndex),
  );
  const [classCount, setClassCount] = useState<number>(
    existingConfig?.classCount ?? 5,
  );
  const [method, setMethod] = useState<ClassificationMethod>(
    existingConfig?.method ?? 'equal_interval',
  );
  // Manual-breaks editor state — seeded from any persisted breaks so a
  // manual config round-trips. Strings so partial/empty edits don't crash.
  const [manualBreakInputs, setManualBreakInputs] = useState<string[]>(
    existingConfig?.method === 'manual' && existingConfig.breaks?.length
      ? existingConfig.breaks.map((b) => String(b))
      : ['', ''],
  );
  const [target, setTarget] = useState<'color' | 'radius' | 'width'>(
    existingConfig?.target ?? 'color',
  );
  const [sizeRange, setSizeRange] = useState<[number, number]>(
    existingConfig?.sizeRange ?? defaultSizeRange(existingConfig?.target ?? 'color'),
  );
  const [reversed, setReversed] = useState<boolean>(
    existingConfig?.reversed ?? false,
  );

  // Phase 20260526-builder-audit BLD-20260526-11: 200ms debounce for per-category / per-class color picker.
  // drags in DataDrivenStyleEditor. The HexColorPicker fires onChange on every
  // drag pixel; debouncing collapses rapid calls into a single map repaint.
  const colorDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

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

  // std-dev classification needs both mean and σ. The current stats endpoint
  // returns `mean` but not `stddev`, so gate the option honestly on availability
  // rather than fabricating σ from the quantiles.
  const stdDevAvailable =
    statsData?.mean != null && statsData?.stddev != null;

  // Parse the manual-breaks editor inputs into numbers (ignoring blank rows),
  // and validate strictly-ascending via manualBreaks. `manualBreaksInvalid`
  // drives the inline warning and prevents writing a broken step expression.
  const manualBreakValues = useMemo(
    () =>
      manualBreakInputs
        .map((s) => s.trim())
        .filter((s) => s !== '')
        .map((s) => Number(s)),
    [manualBreakInputs],
  );
  const manualBreaksInvalid = useMemo(() => {
    if (method !== 'manual') return false;
    if (manualBreakValues.length === 0) return true;
    try {
      return manualBreaks(manualBreakValues).length === 0;
    } catch {
      return true;
    }
  }, [method, manualBreakValues]);

  // Extract narrow paint/config slices so effects don't re-run on every paint change
  const colorPaintProp = useMemo(
    () => layer.paint?.[getColorProperty(layer.dataset_geometry_type)],
    [layer.paint, layer.dataset_geometry_type],
  );
  const sizePaintProp = useMemo(() => {
    const rProp = getSizeProperty(layer.dataset_geometry_type, 'radius');
    const wProp = getSizeProperty(layer.dataset_geometry_type, 'width');
    return rProp ? layer.paint?.[rProp] : wProp ? layer.paint?.[wProp] : undefined;
  }, [layer.paint, layer.dataset_geometry_type]);
  const styleConfig = layer.style_config;
  const layerId = layer.id;
  const geomType = layer.dataset_geometry_type;

  // Cleanup color debounce timer on unmount
  useEffect(() => {
    return () => clearTimeout(colorDebounceRef.current);
  }, []);

  // Effect 1: Categorical styling with value-fetching
  useEffect(() => {
    if (!column || mode !== 'categorical' || !valuesData) return;

    const values = valuesData.values;
    const colorProp = getColorProperty(geomType);

    // Preserve existing per-category colors when column and ramp haven't changed.
    // Treat a missing `reversed` field as false (backward-compatible with saved configs).
    const ec = styleConfig;
    if (
      ec?.mode === 'categorical' &&
      ec.column === column &&
      ec.ramp === ramp &&
      (ec.reversed ?? false) === reversed &&
      ec.categories &&
      ec.categories.length === values.length &&
      ec.categories.every((c, i) => c.value === values[i])
    ) {
      return;
    }

    // Resolve 'custom' to a real ramp when regenerating (e.g., column change)
    const effectiveRamp = ramp === 'custom' ? 'Set2' : ramp;
    if (ramp === 'custom') setRamp(effectiveRamp);

    const rawColors = getRampColors(effectiveRamp, Math.max(values.length, 1));
    const colors = reversed ? reverseRamp(rawColors) : rawColors;
    const valueColorMap: [unknown, string][] = values.map((v, i) => [v, colors[i]]);
    const expression = buildCategoricalExpression(column, valueColorMap, MAP_COLORS.fallback);

    const categories = values.map((v, i) => ({ value: v, color: colors[i] }));
    const config: StyleConfig = { mode: 'categorical', column, ramp: effectiveRamp, reversed, categories };
    const paint = { ...layer.paint, [colorProp]: expression };
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed colorPaintProp covers the relevant slice
  }, [column, mode, ramp, reversed, valuesData, styleConfig, geomType, colorPaintProp, layerId, onStyleConfigChange]);

  // Effect 2: Graduated color styling
  useEffect(() => {
    if (!column || mode !== 'graduated' || !statsData || statsData.min === null || statsData.max === null || !Array.isArray(statsData.quantiles)) return;
    if (target !== 'color' && target) return;

    const { breaks, effectiveClassCount, invalid } = computeBreaks(
      {
        min: statsData.min,
        max: statsData.max,
        quantiles: statsData.quantiles,
        mean: statsData.mean,
        stddev: statsData.stddev,
      },
      method,
      classCount,
      manualBreakValues,
    );

    // Don't write a broken step expression from invalid manual input — the UI
    // shows an inline warning instead. Also bail if there are no usable breaks.
    if (invalid || breaks.length === 0) return;

    // Preserve existing graduated colors when config hasn't changed.
    // Treat a missing `reversed` field as false (backward-compatible with saved configs).
    const ec = styleConfig;
    if (
      ec?.mode === 'graduated' &&
      ec.column === column &&
      ec.ramp === ramp &&
      (ec.reversed ?? false) === reversed &&
      ec.method === method &&
      ec.classCount === classCount &&
      ec.colors &&
      ec.breaks &&
      (method !== 'manual' ||
        (ec.breaks.length === breaks.length &&
          ec.breaks.every((b, i) => b === breaks[i]))) &&
      (!ec.target || ec.target === 'color')
    ) {
      return;
    }

    // Resolve 'custom' to a real ramp when regenerating (e.g., column change)
    const effectiveRamp = ramp === 'custom' ? 'YlOrRd' : ramp;
    if (ramp === 'custom') setRamp(effectiveRamp);

    const rawColors = getRampColors(effectiveRamp, effectiveClassCount);
    const colors = reversed ? reverseRamp(rawColors) : rawColors;
    const colorProp = getColorProperty(geomType);
    const expression = buildGraduatedExpression(column, breaks, colors);

    const config: StyleConfig = {
      mode: 'graduated',
      column,
      ramp: effectiveRamp,
      reversed,
      classCount,
      method,
      breaks,
      colors,
      target: 'color',
    };
    const paint = { ...layer.paint, [colorProp]: expression };
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed colorPaintProp covers the relevant slice
  }, [column, mode, ramp, reversed, classCount, method, target, statsData, styleConfig, geomType, colorPaintProp, layerId, onStyleConfigChange, manualBreakValues]);

  // Effect 3: Graduated size styling (radius or width)
  useEffect(() => {
    if (!column || mode !== 'graduated' || !statsData || statsData.min === null || statsData.max === null || !Array.isArray(statsData.quantiles)) return;
    if (target === 'color' || !target) return;

    const { breaks, effectiveClassCount, invalid } = computeBreaks(
      {
        min: statsData.min,
        max: statsData.max,
        quantiles: statsData.quantiles,
        mean: statsData.mean,
        stddev: statsData.stddev,
      },
      method,
      classCount,
      manualBreakValues,
    );

    if (invalid || breaks.length === 0) return;

    // Guard: skip if existing config already matches — use classCount (local
    // state) consistently in both the guard and the written config to prevent
    // infinite effect loops when effectiveClassCount differs from classCount.
    const ec = styleConfig;
    if (
      ec?.target === target &&
      ec.column === column &&
      ec.method === method &&
      ec.classCount === classCount &&
      ec.sizes &&
      ec.sizeRange &&
      ec.sizeRange[0] === sizeRange[0] &&
      ec.sizeRange[1] === sizeRange[1] &&
      (method !== 'manual' ||
        (ec.breaks?.length === breaks.length &&
          ec.breaks.every((b, i) => b === breaks[i])))
    ) {
      return;
    }

    const sizeProp = getSizeProperty(geomType, target);
    if (!sizeProp) return;

    const sizes = computeSizes(sizeRange, effectiveClassCount);
    const sizeExpression = buildGraduatedSizeExpression(column, breaks, sizes);

    const config: StyleConfig = {
      mode: 'graduated',
      column,
      ramp,
      classCount,
      method,
      breaks,
      target,
      sizes,
      sizeRange,
    };
    // Keep existing color expression + add size expression
    const paint = { ...layer.paint, [sizeProp]: sizeExpression };
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed sizePaintProp covers the relevant slice
  }, [column, mode, ramp, classCount, method, target, sizeRange, statsData, styleConfig, geomType, sizePaintProp, layerId, onStyleConfigChange, manualBreakValues]);

  function handleClear() {
    setColumn('');
    setTarget('color');
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const resetPaint: Record<string, unknown> = {
      ...layer.paint,
      [colorProp]: MAP_COLORS.default.fill,
    };
    // Delete custom boolean props that shouldn't persist after clearing
    delete resetPaint['_fill-disabled'];
    delete resetPaint['_stroke-disabled'];
    delete resetPaint['_fill-opacity-saved'];
    delete resetPaint['_outline-width-saved'];
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
    // ENH-08: suggest a data-appropriate ramp when the user switches modes.
    // This is a mode change (not a first-add), so use the data-character
    // default (index 0) rather than the rotation index.
    setRamp(suggestRampForMode(newMode));
    // Reset color property to flat default to clear stale expressions from previous mode
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const nextPaint: Record<string, unknown> = { ...layer.paint, [colorProp]: MAP_COLORS.default.fill };
    if (newMode === 'categorical') {
      // Categorical does not support size targets — force back to color
      setTarget('color');
      // Reset any size paint property to scalar default
      const radiusProp = getSizeProperty(layer.dataset_geometry_type, 'radius');
      const widthProp = getSizeProperty(layer.dataset_geometry_type, 'width');
      if (radiusProp) nextPaint[radiusProp] = 5;
      if (widthProp) nextPaint[widthProp] = 2;
    }
    onStyleConfigChange(layer.id, null, nextPaint);
  }

  function handleTargetChange(newTarget: 'color' | 'radius' | 'width') {
    setTarget(newTarget);
    setSizeRange(defaultSizeRange(newTarget));
  }

  const layerPaint = layer.paint;

  const handleCategoryColorChange = useCallback(
    (value: string | number | null, newColor: string) => {
      if (!styleConfig?.categories) return;

      const updated = styleConfig.categories.map((c) =>
        c.value === value ? { ...c, color: newColor } : c,
      );
      const colorProp = getColorProperty(geomType);
      const valueColorMap: [unknown, string][] = updated.map((c) => [c.value, c.color]);
      const expression = buildCategoricalExpression(
        styleConfig.column,
        valueColorMap,
        MAP_COLORS.fallback,
      );
      const newConfig: StyleConfig = { ...styleConfig, categories: updated, ramp: 'custom' };
      const paint = { ...layerPaint, [colorProp]: expression };
      // Phase 20260526-builder-audit BLD-20260526-11: 200ms debounce — HexColorPicker fires on every drag pixel.
      clearTimeout(colorDebounceRef.current);
      colorDebounceRef.current = setTimeout(() => {
        onStyleConfigChange(layerId, newConfig, paint);
        setRamp('custom');
      }, 200);
    },
    [styleConfig, geomType, layerPaint, layerId, onStyleConfigChange, colorDebounceRef],
  );

  const handleGraduatedColorChange = useCallback(
    (index: number, newColor: string) => {
      if (!styleConfig?.colors || !styleConfig.breaks) return;

      const updatedColors = [...styleConfig.colors];
      updatedColors[index] = newColor;
      const colorProp = getColorProperty(geomType);
      const expression = buildGraduatedExpression(styleConfig.column, styleConfig.breaks, updatedColors);
      const newConfig: StyleConfig = { ...styleConfig, colors: updatedColors, ramp: 'custom' };
      const paint = { ...layerPaint, [colorProp]: expression };
      // Phase 20260526-builder-audit BLD-20260526-11: 200ms debounce — HexColorPicker fires on every drag pixel.
      clearTimeout(colorDebounceRef.current);
      colorDebounceRef.current = setTimeout(() => {
        onStyleConfigChange(layerId, newConfig, paint);
        setRamp('custom');
      }, 200);
    },
    [styleConfig, geomType, layerPaint, layerId, onStyleConfigChange, colorDebounceRef],
  );

  const hasTooManyCategories =
    mode === 'categorical' && valuesData && valuesData.values.length > 20;
  const noCompatibleColumns = filteredColumns.length === 0;
  const selectedColumnMissing = Boolean(column) && !columns.some((c) => c.name === column);
  const graduatedStatsUnavailable =
    mode === 'graduated' &&
    Boolean(column) &&
    (!statsData || statsData.min === null || statsData.max === null || !Array.isArray(statsData.quantiles));

  const showTargetSelector = availableTargets.length > 1 && mode === 'graduated';
  const isSizeTarget = target !== 'color' && mode === 'graduated';

  return (
    <div className="space-y-2.5">
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
      <p className="text-[11px] leading-snug text-muted-foreground">
        {t('dataDriven.scopeHelp')}
      </p>

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

      {noCompatibleColumns && (
        <p className="rounded-md bg-muted px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
          {mode === 'categorical'
            ? t('dataDriven.noTextColumnsHelp')
            : t('dataDriven.noNumericColumnsHelp')}
        </p>
      )}

      {selectedColumnMissing && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-[11px] leading-snug text-warning-foreground">
          {t('dataDriven.missingColumnHelp', { column })}
        </p>
      )}

      {graduatedStatsUnavailable && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-[11px] leading-snug text-warning-foreground">
          {t('dataDriven.statsUnavailableHelp')}
        </p>
      )}

      {/* Color ramp — only shown for color target */}
      {column && !isSizeTarget && (
        <>
          <div className="text-xs text-muted-foreground">{t('dataDriven.colorRamp')}</div>
          <ColorRampPicker
            rampName={ramp}
            onChange={setRamp}
            mode={mode}
            customColors={ramp === 'custom' && layer.style_config?.colors ? layer.style_config.colors : undefined}
            count={mode === 'graduated' ? classCount : undefined}
            reversed={reversed}
            onReversedChange={setReversed}
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
              <div key={String(cat.value)} className="flex items-center gap-2">
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
            <Select value={method} onValueChange={(v) => setMethod(v as ClassificationMethod)}>
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
                <SelectItem value="jenks" className="text-xs">
                  {t('dataDriven.methodJenks')}
                </SelectItem>
                {/* std-dev needs mean + σ; disable honestly when σ is unavailable
                    rather than fabricating it from the quantiles. */}
                <SelectItem value="std_dev" className="text-xs" disabled={!stdDevAvailable}>
                  {t('dataDriven.methodStdDev')}
                </SelectItem>
                <SelectItem value="manual" className="text-xs">
                  {t('dataDriven.methodManual')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Class-count slider — drives the count for the count-based methods. */}
          {(method === 'equal_interval' || method === 'jenks' || method === 'std_dev') && (
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

          {/* Jenks operates on the server quantile sample, not the raw column —
              label that honestly so users don't over-trust the precision. */}
          {method === 'jenks' && (
            <p className="text-[11px] leading-snug text-muted-foreground">
              {t('dataDriven.jenksSampledHint')}
            </p>
          )}

          {/* Manual-breaks editor: a small editable list of numeric inputs. */}
          {method === 'manual' && (
            <div className="space-y-1.5">
              <span className="text-xs text-muted-foreground">{t('dataDriven.manualBreaksLabel')}</span>
              <div className="space-y-1">
                {manualBreakInputs.map((val, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      type="number"
                      inputMode="decimal"
                      value={val}
                      aria-label={t('dataDriven.manualBreaksRowLabel', { index: i + 1 })}
                      onChange={(e) =>
                        setManualBreakInputs((rows) =>
                          rows.map((r, ri) => (ri === i ? e.target.value : r)),
                        )
                      }
                      className="h-7 flex-1 rounded border border-border bg-background px-2 text-xs text-foreground"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0"
                      disabled={manualBreakInputs.length <= 1}
                      onClick={() =>
                        setManualBreakInputs((rows) => rows.filter((_, ri) => ri !== i))
                      }
                      title={t('dataDriven.manualBreaksRemoveRow')}
                      aria-label={t('dataDriven.manualBreaksRemoveRow')}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setManualBreakInputs((rows) => [...rows, ''])}
              >
                {t('dataDriven.manualBreaksAddRow')}
              </Button>
              {manualBreaksInvalid && (
                <p className="rounded-md bg-warning/15 px-2 py-1.5 text-[11px] leading-snug text-warning-foreground">
                  {t('dataDriven.manualBreaksInvalid')}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {hasTooManyCategories && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-[11px] leading-snug text-warning-foreground">
          {t('dataDriven.categoriesWarning', { count: valuesData.values.length })}
        </p>
      )}
    </div>
  );
}
