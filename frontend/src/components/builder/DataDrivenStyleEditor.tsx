import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { SwatchColorPopover } from './StyleColorPicker';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { ColorRampPicker } from './ColorRampPicker';
import { useColumnValues, useColumnStats } from '@/hooks/use-maps';
import {
  getRampColors,
  reverseRamp,
  buildCategoricalExpression,
  categoricalFallbackOf,
  buildGraduatedExpression,
  buildGraduatedSizeExpression,
  getColorProperty,
  getSizeProperty,
  colorClassificationIsOrphaned,
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
import { isGenericGeometryType } from '@/components/builder/layer-adapters/shared';
import { isBooleanColumn, isIntegerColumn, isNumericColumn } from '@/lib/column-utils';
import { useAttributes } from '@/components/dataset/hooks/use-dataset';
import { valueLabelFor, valueLabelsByField } from '@/lib/value-labels';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

interface DataDrivenStyleEditorProps {
  layer: MapLayerResponse;
  onStyleConfigChange: (
    layerId: string,
    config: StyleConfig | null,
    paint: Record<string, unknown>,
    opts?: { replace?: boolean },
  ) => void;
  /**
   * Zero-based ordinal of this layer within the map's data-driven layer set,
   * used to rotate the default palette so successive new layers don't share
   * colors. Defaults to 0. Affects only fresh layers (no existingConfig.ramp);
   * saved layers keep their persisted ramp.
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
 * Compute classification breaks and the effective class count, shared by the
 * graduated-color and graduated-size effects.
 * - quantile: uses precomputed quantiles when available (class count becomes
 *   breaks.length + 1, since each break separates two classes)
 * - equal-interval: respects the requested classCount exactly
 * - jenks: natural breaks over the sample (server quantiles); the raw column
 *   isn't client-side, so this is sampled, not exact
 * - std_dev: mean ± σ steps; only valid when stddev is available (gated in UI)
 * - manual: user-supplied ascending breaks; invalid input yields the previous
 *   valid set with `invalid: true` so the caller can warn instead of writing a
 *   broken step expression
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
  // MapLibre step expressions need strictly ascending breaks; heavily clustered
  // data can yield duplicate quantile boundaries.
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

// API/AI-authored (seeded) graduated configs often omit classCount and
// sizeRange since colors/sizes/breaks imply them. Derive them so
// styleConfigAlreadyMatches (and local state seeded from the same config)
// treats a complete seeded config as matching rather than drift to regenerate.
//
// A config can carry both colors and sizes (e.g. a double-encoded
// graduated-radius layer) whose lengths diverge; `preferSizes` lets a
// size-target caller derive from `sizes.length` instead of `colors.length`.
function effectiveClassCountOf(
  cfg: StyleConfig | null | undefined,
  preferSizes = false,
): number | undefined {
  if (!cfg) return undefined;
  if (cfg.classCount != null) return cfg.classCount;
  const bySizes = cfg.sizes?.length;
  const byColors = cfg.colors?.length;
  if (preferSizes && bySizes) return bySizes;
  if (byColors) return byColors;
  if (bySizes) return bySizes;
  if (cfg.breaks) return cfg.breaks.length + 1;
  return undefined;
}

function effectiveSizeRangeOf(cfg: StyleConfig | null | undefined): [number, number] | undefined {
  if (!cfg) return undefined;
  if (cfg.sizeRange) return cfg.sizeRange;
  if (cfg.sizes?.length) return [cfg.sizes[0], cfg.sizes[cfg.sizes.length - 1]];
  return undefined;
}

/**
 * The three styling effects (categorical color, graduated color, graduated
 * size) each write canonical style via onStyleConfigChange, guarded by a
 * deep-equality skip-check whose only job is to prevent an infinite
 * onStyleConfigChange -> re-render -> effect loop. This one parameterized
 * helper (mode, target) is the tested place those guards live; it returns true
 * when the existing config already matches what the effect would write. A field
 * missed here means an infinite loop or stale style.
 */
interface StyleGuardParams {
  existing: StyleConfig | null | undefined;
  mode: 'categorical' | 'graduated';
  target: 'color' | 'radius' | 'width';
  column: string;
  ramp: string;
  reversed: boolean;
  method: ClassificationMethod;
  classCount: number;
  /** Computed breaks for the candidate write (graduated); [] for categorical. */
  breaks: number[];
  /** Candidate size range (graduated size only). */
  sizeRange: [number, number];
  /** Candidate category values, in order (categorical only). */
  categoryValues?: unknown[];
}

export function styleConfigAlreadyMatches(p: StyleGuardParams): boolean {
  const ec = p.existing;
  if (!ec) return false;

  // Categorical color
  if (p.mode === 'categorical') {
    const values = p.categoryValues ?? [];
    const dataValues = new Set(values);
    // Clobber-on-open: skip the regenerate when every styled category still
    // exists in the data, even if the data has additional distinct values the
    // saved config never listed. Requiring exact length+order equality would
    // regenerate colors from the ramp merely on opening the editor, discarding
    // hand-authored per-category colors/labels. Unlisted values fall through to
    // the paint expression's own fallback. A stale category no longer in the
    // data still fails the check, so a drifted config regenerates.
    //
    // With no distinct values the effect writes `categories: []`; that empty
    // config must count as a match or it re-writes every render (empty
    // dataset / all-null column). So for empty data, match iff the saved
    // categories are also empty; for non-empty data, require a non-empty
    // subset (an empty config still regenerates to style the values).
    const categoriesSettled =
      values.length === 0
        ? ec.categories?.length === 0
        : (ec.categories?.length ?? 0) > 0 &&
          ec.categories!.every((c) => dataValues.has(c.value));
    return Boolean(
      ec.mode === 'categorical' &&
      ec.column === p.column &&
      ec.ramp === p.ramp &&
      (ec.reversed ?? false) === p.reversed &&
      ec.categories &&
      categoriesSettled,
    );
  }

  // Graduated color
  if (p.target === 'color') {
    return Boolean(
      ec.mode === 'graduated' &&
      ec.column === p.column &&
      ec.ramp === p.ramp &&
      (ec.reversed ?? false) === p.reversed &&
      ec.method === p.method &&
      effectiveClassCountOf(ec) === p.classCount &&
      ec.colors &&
      ec.breaks &&
      (p.method !== 'manual' ||
        (ec.breaks.length === p.breaks.length &&
          ec.breaks.every((b, i) => b === p.breaks[i]))) &&
      (!ec.target || ec.target === 'color'),
    );
  }

  // Graduated size (radius or width)
  {
    const ecSizeRange = effectiveSizeRangeOf(ec);
    return Boolean(
      ec.target === p.target &&
      ec.column === p.column &&
      ec.method === p.method &&
      // Size-target branch: derive classCount from sizes.length, not
      // colors.length, for a config that carries both.
      effectiveClassCountOf(ec, true) === p.classCount &&
      ec.sizes &&
      ecSizeRange &&
      ecSizeRange[0] === p.sizeRange[0] &&
      ecSizeRange[1] === p.sizeRange[1] &&
      (p.method !== 'manual' ||
        (ec.breaks?.length === p.breaks.length &&
          (ec.breaks ?? []).every((b, i) => b === p.breaks[i]))),
    );
  }
}

// When a line layer's color switches to a data-driven solid color, a stale
// `line-gradient` paint entry is incompatible and must be dropped from the
// candidate paint. No-op for non-line color props. The `builder.lineGradient`
// intent stub is cleared centrally in handleStyleConfigChange
// (use-layer-map-sync.ts).
function stripStaleLineGradient(
  paint: Record<string, unknown>,
  colorProp: string,
): Record<string, unknown> {
  if (colorProp !== 'line-color' || !('line-gradient' in paint)) return paint;
  const { 'line-gradient': _droppedGradient, ...rest } = paint;
  return rest;
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
  // Fresh layers (no saved ramp) get a rotating default palette so successive
  // adds don't share a color. Saved layers keep their persisted ramp.
  const [ramp, setRamp] = useState<string>(
    existingConfig?.ramp ?? nextRotatingRamp(existingConfig?.mode ?? 'categorical', rampRotationIndex),
  );
  // Derive classCount/sizeRange from a persisted config only when it is in
  // graduated mode: a `mode: 'categorical'` config can carry stray
  // graduated-shaped fields (StyleConfig is an open bag), which would poison a
  // later switch back to graduated.
  const [classCount, setClassCount] = useState<number>(
    existingConfig?.mode === 'graduated'
      ? existingConfig?.classCount ??
          effectiveClassCountOf(existingConfig, existingConfig?.target !== 'color') ??
          5
      : 5,
  );
  const [method, setMethod] = useState<ClassificationMethod>(
    existingConfig?.method ?? 'equal_interval',
  );
  // Manual-breaks editor state, seeded from persisted breaks so a manual config
  // round-trips. Strings so partial/empty edits don't crash.
  const [manualBreakInputs, setManualBreakInputs] = useState<string[]>(
    existingConfig?.method === 'manual' && existingConfig.breaks?.length
      ? existingConfig.breaks.map((b) => String(b))
      : ['', ''],
  );
  const [target, setTarget] = useState<'color' | 'radius' | 'width'>(
    existingConfig?.target ?? 'color',
  );
  const [sizeRange, setSizeRange] = useState<[number, number]>(
    existingConfig?.mode === 'graduated'
      ? existingConfig?.sizeRange ??
          effectiveSizeRangeOf(existingConfig) ??
          defaultSizeRange(existingConfig?.target ?? 'color')
      : defaultSizeRange(existingConfig?.target ?? 'color'),
  );
  const [reversed, setReversed] = useState<boolean>(
    existingConfig?.reversed ?? false,
  );

  // 200ms debounce for per-category / per-class color picker drags:
  // HexColorPicker fires onChange on every drag pixel; this collapses rapid
  // calls into one map repaint.
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
  // Booleans classify as the strings "true"/"false" (a match label can't be a boolean).
  // Integer columns classify by their numeric codes. A float column stays listed only
  // while the saved style is categorical on it (an imported coded-value field).
  const savedCategoricalColumn =
    layer.style_config?.mode === 'categorical' ? layer.style_config.column : undefined;
  const textColumns = columns.filter(
    (c) => isTextColumn(c.type) ||
      isBooleanColumn(c.type) ||
      isIntegerColumn(c.type) ||
      c.name === savedCategoricalColumn,
  );
  const columnIsBoolean = columns.some((c) => c.name === column && isBooleanColumn(c.type));
  const columnIsInteger = columns.some((c) => c.name === column && isIntegerColumn(c.type));
  const numericColumns = columns.filter((c) => isNumericColumn(c.type));
  const filteredColumns = mode === 'categorical' ? textColumns : numericColumns;

  const columnForCategorical = mode === 'categorical' && column ? column : undefined;
  const columnForGraduated = mode === 'graduated' && column ? column : undefined;

  const { data: valuesData } = useColumnValues(
    columnForCategorical ? layer.dataset_id : undefined,
    columnForCategorical,
  );
  // Categorical mode needs the stats endpoint too: useColumnValues pages at 100
  // (500 max), so its length is a page size, not a cardinality. `distinct_count`
  // is exact and full-table.
  const columnForStats = columnForGraduated ?? columnForCategorical;
  const { data: statsData } = useColumnStats(
    columnForStats ? layer.dataset_id : undefined,
    columnForStats,
  );

  // Value labels come from the attribute metadata; a coded column waits for it
  // so its first generated classes already carry their labels.
  const { data: attributeList, isPending: attributesPending } = useAttributes(
    columnIsInteger ? layer.dataset_id : undefined,
  );
  const valueLabels = useMemo(
    () => valueLabelsByField(attributeList?.attributes).get(column),
    [attributeList, column],
  );

  // std-dev classification needs mean and σ. The stats endpoint returns `mean`
  // but not `stddev`, so the option is gated on availability, not fabricated
  // from quantiles.
  const stdDevAvailable =
    statsData?.mean != null && statsData?.stddev != null;

  // Parse the manual-breaks inputs into numbers (ignoring blank rows) and
  // validate strictly ascending via manualBreaks. `manualBreaksInvalid` drives
  // the inline warning and blocks writing a broken step expression.
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

  // The classification lives in three places: the paint expression,
  // `style_config`, and this component's local `column`/`mode` state. A
  // classification can be retired from outside this editor (the commit
  // boundary retires one whose expression a paint replacement removed; Reset
  // destroys one), and the effects regenerate from local state alone, so they
  // would re-assert it and overwrite the paint the user just replaced.
  //
  // So follow the layer: clearing `column` is enough, since all three effects
  // bail on it (as this editor's own clear paths do). This is React's
  // adjust-state-during-render pattern rather than an effect on purpose: React
  // re-runs the component before any effect, so effect 1 never gets a pass with
  // a stale column; an effect here would lose the race.
  const configClaimsClassification = !!styleConfig?.mode;
  const [claimedLastRender, setClaimedLastRender] = useState(configClaimsClassification);
  if (configClaimsClassification !== claimedLastRender) {
    setClaimedLastRender(configClaimsClassification);
    // Retired, not established: a first-time column choice moves the other way,
    // with local state legitimately ahead of a config the effects will write.
    if (!configClaimsClassification && column) setColumn('');
  }

  // Effect 1: Categorical styling with value-fetching
  useEffect(() => {
    if (!column || mode !== 'categorical' || !valuesData) return;
    if (columnIsInteger && attributesPending) return;

    // Boolean columns arrive as true/false; classify them by their string form.
    const values = columnIsBoolean
      ? valuesData.values.map((v) => String(v))
      : valuesData.values.filter((v) => typeof v !== 'boolean');
    const colorProp = getColorProperty(geomType);

    // Preserve existing per-category colors when column and ramp haven't
    // changed (skip-guard: styleConfigAlreadyMatches).
    //
    // That guard compares the saved config against this effect's own state,
    // assuming paint agrees with config; an orphaned classification is that
    // assumption failing. A layer can arrive orphaned from storage (saved before
    // the boundary rule, or written through the API/SDK/AI), where the editor
    // would skip regenerating and report attribute styling on a flat-colour
    // layer. Regenerating is also the repair.
    if (!colorClassificationIsOrphaned(styleConfig, layer.paint ?? {}, geomType) &&
      styleConfigAlreadyMatches({
      existing: styleConfig,
      mode: 'categorical',
      target: 'color',
      column,
      ramp,
      reversed,
      method,
      classCount,
      breaks: [],
      sizeRange,
      categoryValues: values,
      })
    ) {
      return;
    }

    // Resolve 'custom' to a real ramp when regenerating (e.g. column change)
    const effectiveRamp = ramp === 'custom' ? 'Set2' : ramp;
    if (ramp === 'custom') setRamp(effectiveRamp);

    const rawColors = getRampColors(effectiveRamp, Math.max(values.length, 1));
    const colors = reversed ? reverseRamp(rawColors) : rawColors;
    const valueColorMap: [unknown, string][] = values.map((v, i) => [v, colors[i]]);
    const expression = buildCategoricalExpression(column, valueColorMap, MAP_COLORS.fallback, columnIsBoolean);

    const categories = values.map((v, i) => {
      const label = valueLabelFor(valueLabels, v);
      return { value: v, ...(label !== undefined ? { label } : {}), color: colors[i] };
    });
    const config: StyleConfig = { mode: 'categorical', column, ramp: effectiveRamp, reversed, categories };
    const paint = stripStaleLineGradient({ ...layer.paint, [colorProp]: expression }, colorProp);
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed colorPaintProp covers the relevant slice
  }, [column, mode, ramp, reversed, valuesData, columnIsBoolean, columnIsInteger, attributesPending, valueLabels, styleConfig, geomType, colorPaintProp, layerId, onStyleConfigChange]);

  // Effect 2: Graduated color styling
  useEffect(() => {
    if (!column || mode !== 'graduated' || !statsData || statsData.min == null || statsData.max == null || !Array.isArray(statsData.quantiles)) return;
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

    // Don't write a broken step expression from invalid manual input (the UI
    // shows an inline warning) or when there are no usable breaks.
    if (invalid || breaks.length === 0) return;

    // Preserve existing graduated colors when config hasn't changed
    // (styleConfigAlreadyMatches), but never skip on an orphaned config (effect 1).
    if (!colorClassificationIsOrphaned(styleConfig, layer.paint ?? {}, geomType) &&
      styleConfigAlreadyMatches({
        existing: styleConfig,
        mode: 'graduated',
        target: 'color',
        column,
        ramp,
        reversed,
        method,
        classCount,
        breaks,
        sizeRange,
      })
    ) {
      return;
    }

    // Resolve 'custom' to a real ramp when regenerating (e.g. column change)
    const effectiveRamp = ramp === 'custom' ? 'YlOrRd' : ramp;
    if (ramp === 'custom') setRamp(effectiveRamp);

    const rawColors = getRampColors(effectiveRamp, effectiveClassCount);
    const colors = reversed ? reverseRamp(rawColors) : rawColors;
    const colorProp = getColorProperty(geomType);
    const nullColor = styleConfig?.column === column ? styleConfig.nullColor : undefined;
    const expression = buildGraduatedExpression(column, breaks, colors, nullColor);

    const config: StyleConfig = {
      mode: 'graduated',
      column,
      ramp: effectiveRamp,
      reversed,
      classCount,
      method,
      breaks,
      colors,
      ...(nullColor ? { nullColor } : {}),
      target: 'color',
    };
    const paint = stripStaleLineGradient({ ...layer.paint, [colorProp]: expression }, colorProp);
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed colorPaintProp covers the relevant slice
  }, [column, mode, ramp, reversed, classCount, method, target, statsData, styleConfig, geomType, colorPaintProp, layerId, onStyleConfigChange, manualBreakValues]);

  // Effect 3: Graduated size styling (radius or width)
  useEffect(() => {
    if (!column || mode !== 'graduated' || !statsData || statsData.min == null || statsData.max == null || !Array.isArray(statsData.quantiles)) return;
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

    // Skip if the existing config already matches (styleConfigAlreadyMatches).
    // It uses classCount (local state) consistently with the config written
    // below, preventing effect loops when effectiveClassCount differs.
    if (styleConfigAlreadyMatches({
      existing: styleConfig,
      mode: 'graduated',
      target,
      column,
      ramp,
      reversed,
      method,
      classCount,
      breaks,
      sizeRange,
    })) {
      return;
    }

    const sizeProp = getSizeProperty(geomType, target);
    if (!sizeProp) return;

    const sizes = computeSizes(sizeRange, effectiveClassCount);
    const sizeExpression = buildGraduatedSizeExpression(column, breaks, sizes);

    const nullColor = styleConfig?.column === column ? styleConfig.nullColor : undefined;
    const config: StyleConfig = {
      mode: 'graduated',
      column,
      ramp,
      classCount,
      method,
      breaks,
      ...(nullColor ? { nullColor } : {}),
      target,
      sizes,
      sizeRange,
    };
    // Keep existing color expression + add size expression
    const paint = { ...layer.paint, [sizeProp]: sizeExpression };
    onStyleConfigChange(layerId, config, paint);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layer.paint excluded: narrowed sizePaintProp covers the relevant slice
  }, [column, mode, ramp, classCount, method, target, sizeRange, statsData, styleConfig, geomType, sizePaintProp, layerId, onStyleConfigChange, manualBreakValues]);

  /**
   * What the clear paths owe a patterned layer.
   *
   * Dropping the pattern alone would make an exploratory Mode switch
   * destructive: red hatching would become default blue, the red surviving only
   * in the stash. So restore the stashed colour as the solid fill and clear the
   * stash. The pattern must still go, since a defaulted fill-color loses to a
   * surviving fill-pattern and the layer would read as cleared while still
   * patterned.
   *
   * Clearing the stash needs `replace`: these paths write a null config, which
   * handleStyleConfigChange reads as "keep the existing builder".
   */
  function clearedFillPaint(paint: Record<string, unknown>, colorProp: string) {
    const next = { ...paint };
    const stashed = layer.style_config?.builder?.fillColorSaved;
    const hadPattern = next['fill-pattern'] != null;
    delete next['fill-pattern'];
    next[colorProp] = (hadPattern && typeof stashed === 'string' ? stashed : null)
      ?? MAP_COLORS.default.fill;
    return next;
  }

  /** The builder block minus the pattern colour stash, or null when nothing is left. */
  function clearedConfig(): StyleConfig | null {
    const builder = layer.style_config?.builder;
    if (!builder) return null;
    const rest = Object.fromEntries(
      Object.entries(builder).filter(([k, v]) => k !== 'fillColorSaved' && v !== undefined),
    );
    return Object.keys(rest).length > 0 ? ({ builder: rest } as StyleConfig) : null;
  }

  function handleClear() {
    setColumn('');
    setTarget('color');
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const resetPaint = clearedFillPaint(layer.paint, colorProp);
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
    onStyleConfigChange(layer.id, clearedConfig(), resetPaint, { replace: true });
  }

  function handleColumnChange(newColumn: string) {
    if (!newColumn) {
      setColumn('');
      const colorProp = getColorProperty(layer.dataset_geometry_type);
      const basePaint = clearedFillPaint(layer.paint, colorProp);
      onStyleConfigChange(layer.id, clearedConfig(), basePaint, { replace: true });
    } else {
      setColumn(newColumn);
    }
  }

  function handleModeChange(newMode: 'categorical' | 'graduated') {
    setMode(newMode);
    setColumn('');
    // Suggest a data-appropriate ramp on a mode change (not a first add), so
    // use the data-character default (index 0), not the rotation index.
    setRamp(suggestRampForMode(newMode));
    // Reset color property to flat default to clear stale expressions
    const colorProp = getColorProperty(layer.dataset_geometry_type);
    const nextPaint = clearedFillPaint(layer.paint, colorProp);
    if (newMode === 'categorical') {
      // Categorical doesn't support size targets: force back to color
      setTarget('color');
      // Reset any size paint property to scalar default
      const radiusProp = getSizeProperty(layer.dataset_geometry_type, 'radius');
      const widthProp = getSizeProperty(layer.dataset_geometry_type, 'width');
      if (radiusProp) nextPaint[radiusProp] = 5;
      if (widthProp) nextPaint[widthProp] = 2;
    } else {
      // Reset to defaults so a later graduated session starts clean, not from
      // classCount/sizeRange derived from stray graduated-shaped fields on a
      // categorical config at mount.
      setClassCount(5);
      setSizeRange(defaultSizeRange('color'));
    }
    onStyleConfigChange(layer.id, clearedConfig(), nextPaint, { replace: true });
  }

  function handleTargetChange(newTarget: 'color' | 'radius' | 'width') {
    setTarget(newTarget);
    setSizeRange(defaultSizeRange(newTarget));
  }

  const layerPaint = layer.paint;

  const handleCategoryColorChange = useCallback(
    (value: string | number | null, newColor: string) => {
      if (!styleConfig?.categories || !styleConfig.column) return;

      const updated = styleConfig.categories.map((c) =>
        c.value === value ? { ...c, color: newColor } : c,
      );
      const colorProp = getColorProperty(geomType);
      const valueColorMap: [unknown, string][] = updated.map((c) => [c.value, c.color]);
      const expression = buildCategoricalExpression(
        styleConfig.column,
        valueColorMap,
        // Keep a catch-all colour set elsewhere (a QGIS publish, the style JSON).
        categoricalFallbackOf(layerPaint[colorProp]) ?? MAP_COLORS.fallback,
        columnIsBoolean,
      );
      const newConfig: StyleConfig = { ...styleConfig, categories: updated, ramp: 'custom' };
      const paint = { ...layerPaint, [colorProp]: expression };
      // 200ms debounce — HexColorPicker fires on every drag pixel.
      clearTimeout(colorDebounceRef.current);
      colorDebounceRef.current = setTimeout(() => {
        onStyleConfigChange(layerId, newConfig, paint);
        setRamp('custom');
      }, 200);
    },
    [styleConfig, geomType, layerPaint, layerId, onStyleConfigChange, colorDebounceRef, columnIsBoolean],
  );

  const handleGraduatedColorChange = useCallback(
    (index: number, newColor: string) => {
      if (!styleConfig?.colors || !styleConfig.breaks || !styleConfig.column) return;

      const updatedColors = [...styleConfig.colors];
      updatedColors[index] = newColor;
      const colorProp = getColorProperty(geomType);
      const expression = buildGraduatedExpression(
        styleConfig.column,
        styleConfig.breaks,
        updatedColors,
        styleConfig.nullColor,
      );
      const newConfig: StyleConfig = { ...styleConfig, colors: updatedColors, ramp: 'custom' };
      const paint = { ...layerPaint, [colorProp]: expression };
      // 200ms debounce — HexColorPicker fires on every drag pixel.
      clearTimeout(colorDebounceRef.current);
      colorDebounceRef.current = setTimeout(() => {
        onStyleConfigChange(layerId, newConfig, paint);
        setRamp('custom');
      }, 200);
    },
    [styleConfig, geomType, layerPaint, layerId, onStyleConfigChange, colorDebounceRef],
  );

  // `values` is one page (100 default, 500 max); `distinct_count` is the exact
  // full-table cardinality. The advice triggers on the true count, and the copy
  // says so when the swatch list is only a prefix of it.
  const shownCategories = valuesData?.values.length ?? 0;
  const distinctCategories = mode === 'categorical' ? statsData?.distinct_count ?? null : null;
  const totalCategories = distinctCategories ?? shownCategories;
  const categoriesTruncated = distinctCategories != null && distinctCategories > shownCategories;
  const hasTooManyCategories =
    mode === 'categorical' && !!valuesData && totalCategories > 20;
  // The mixed-adapter predicate, not classifyGeometry(...) === 'other': both
  // catch GEOMETRY / GEOMETRYCOLLECTION, but 'other' also swallows null and
  // exotic types like CURVE, which resolveAdapterType routes to the plain fill
  // adapter. Telling those layers their line and point sublayers keep their
  // colours would describe sublayers that don't exist.
  const isMixedGeometry = isGenericGeometryType(layer.dataset_geometry_type);
  const noCompatibleColumns = filteredColumns.length === 0;
  const selectedColumnMissing = Boolean(column) && !columns.some((c) => c.name === column);
  const graduatedStatsUnavailable =
    mode === 'graduated' &&
    Boolean(column) &&
    (!statsData || statsData.min == null || statsData.max == null || !Array.isArray(statsData.quantiles));

  const showTargetSelector = availableTargets.length > 1 && mode === 'graduated';
  const isSizeTarget = target !== 'color' && mode === 'graduated';

  return (
    <div className="space-y-2.5">
      {column && (
        <div className="flex justify-end">
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
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-20">{t('dataDriven.mode')}</span>
        <Select value={mode} onValueChange={(v) => handleModeChange(v as 'categorical' | 'graduated')}>
          <SelectTrigger className="h-7 text-xs flex-1" aria-label={t('dataDriven.mode')}>
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
            <SelectTrigger className="h-7 text-xs flex-1" aria-label={t('dataDriven.target')}>
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
          <SelectTrigger className="h-7 text-xs flex-1" aria-label={t('dataDriven.column')}>
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
        <p className="rounded-md bg-muted px-2 py-1.5 text-mini leading-snug text-muted-foreground">
          {mode === 'categorical'
            ? t('dataDriven.noTextColumnsHelp')
            : t('dataDriven.noNumericColumnsHelp')}
        </p>
      )}

      {/* A ramp on a mixed-geometry layer writes one colour property, chosen by
          geometry ('other' resolves to fill-color), and the mixed adapter filters
          that key out of the line and circle sublayers. So only polygons
          classify while the legend shows the full classification. Say which
          features the colours reach so the mismatch is explicable. */}
      {isMixedGeometry && (
        <p className="rounded-md bg-muted px-2 py-1.5 text-mini leading-snug text-muted-foreground">
          {t('dataDriven.mixedGeometryColorScope')}
        </p>
      )}

      {/* Mode defaults to Categorical, whose Column dropdown lists only text
          columns, so numeric columns (e.g. `mag`) would be invisible with no hint.
          Surface a persistent pointer whenever numeric columns exist but are
          hidden by Categorical mode, so graduated styling is discoverable. */}
      {mode === 'categorical' && numericColumns.length > 0 && (
        <p className="rounded-md bg-muted px-2 py-1.5 text-mini leading-snug text-muted-foreground">
          {t('dataDriven.numericColumnsAvailable', { count: numericColumns.length })}{' '}
          <button
            type="button"
            className="font-medium text-foreground underline underline-offset-2 hover:no-underline"
            onClick={() => handleModeChange('graduated')}
          >
            {t('dataDriven.switchToGraduated')}
          </button>
        </p>
      )}

      {selectedColumnMissing && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-mini leading-snug text-warning">
          {t('dataDriven.missingColumnHelp', { column })}
        </p>
      )}

      {graduatedStatsUnavailable && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-mini leading-snug text-warning">
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
              aria-label={t('dataDriven.sizeMin')}
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
              aria-label={t('dataDriven.sizeMax')}
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
                <SwatchColorPopover
                  color={cat.color}
                  onChange={(hex) => handleCategoryColorChange(cat.value, hex)}
                />
                <span className="text-xs truncate">
                  {cat.label && cat.label !== String(cat.value) ? `${cat.label} (${cat.value})` : cat.value}
                </span>
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
                  <SwatchColorPopover
                    color={color}
                    onChange={(hex) => handleGraduatedColorChange(i, hex)}
                  />
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
              <SelectTrigger className="h-7 text-xs flex-1" aria-label={t('dataDriven.method')}>
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
                {/* std-dev needs mean + σ; disabled when σ is unavailable. */}
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
                aria-label={t('dataDriven.classes')}
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

          {/* Jenks operates on the server quantile sample, not the raw column;
              label that so users don't over-trust the precision. */}
          {method === 'jenks' && (
            <p className="text-mini leading-snug text-muted-foreground">
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
                      className="h-7 flex-1 rounded-sm border border-border bg-background px-2 text-xs text-foreground"
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
                <p className="rounded-md bg-warning/15 px-2 py-1.5 text-mini leading-snug text-warning">
                  {t('dataDriven.manualBreaksInvalid')}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {hasTooManyCategories && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-mini leading-snug text-warning">
          {categoriesTruncated
            ? t('dataDriven.categoriesTruncatedWarning', {
                count: totalCategories,
                shown: shownCategories,
              })
            : t('dataDriven.categoriesWarning', { count: totalCategories })}
        </p>
      )}
    </div>
  );
}
