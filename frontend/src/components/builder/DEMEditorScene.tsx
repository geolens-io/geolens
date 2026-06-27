import { memo, useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { StyleColorPicker } from './StyleColorPicker';
import { ColorRampPicker } from './ColorRampPicker';
import { SunCompass } from './SunCompass';
import { getNumberPaint, getStringPaint } from './paint-accessors';
import {
  HILLSHADE_EXAGGERATION_MAX,
  HILLSHADE_EXAGGERATION_MIN,
  HILLSHADE_PAINT_DEFAULTS,
  normalizeHillshadeExaggeration,
} from './layer-adapters/hillshade-adapter';
import {
  TERRAIN_EXAGGERATION_MAX,
  TERRAIN_EXAGGERATION_MIN,
  normalizeTerrainExaggeration,
} from './map-sync';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

/** DEM render mode union. Assignable to StyleConfig['render_mode'] without cast. */
export type DemRenderMode = 'hillshade' | 'terrain';

export interface DEMEditorSceneProps {
  layer: MapLayerResponse;
  // Render mode is derived from layer.style_config.render_mode by the component.
  // Missing/legacy image DEM modes are treated as hillshade because raw DEM
  // image tiles are encoded elevation data, not inspectable imagery.
  onPaintChange: (paint: Record<string, unknown>) => void;
  onStyleConfigChange: (config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onOpacityChange: (opacity: number) => void;
  onZoomChange: (min: number, max: number) => void;
  /** Called when the user switches to Terrain mode. Wires map-level terrain_config
   * via use-builder-layers handleDEMTerrainBind. */
  onTerrainBind: (layerId: string) => void;
  /** Called when the user switches this DEM away from Terrain mode. */
  onTerrainUnbind: (layerId: string) => void;
  /** Terrain surface exaggeration belongs to the bound DEM layer editor. */
  terrainExaggeration: number;
  onTerrainExaggerationChange: (layerId: string, exaggeration: number) => void;
  /** Called after the user confirms deletion. Matches the onRemove pattern in
   * LayerEditorHandlers — same wiring used by the default layer editor. */
  onRemove: (layerId: string) => void;
  /**
   * POLISH-02 / builder-audit #338 YAGNI-01: when true, this DEM is already powering the
   * map's terrain source. A muted advisory note is rendered in hillshade mode to inform
   * the user that hillshade shading is hidden (two raster-dem consumers on one source
   * cause MapLibre errors). Defaults to false when omitted.
   */
  isTerrainBound?: boolean;
}

function currentMode(layer: MapLayerResponse): DemRenderMode {
  return effectiveDemRenderMode(layer.style_config, layer.is_dem) === 'terrain'
    ? 'terrain'
    : 'hillshade';
}

function clampZoom(v: number): number {
  return Math.max(0, Math.min(22, Math.round(v)));
}

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange: (v: number) => void;
  ariaLabel: string;
  showInput?: boolean;
}

function formatSliderValue(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function clampToStep(value: number, min: number, max: number, step: number) {
  const clamped = Math.min(Math.max(value, min), max);
  if (!Number.isFinite(step) || step <= 0) return clamped;
  const decimals = String(step).split('.')[1]?.length ?? 0;
  return Number((Math.round((clamped - min) / step) * step + min).toFixed(decimals));
}

function SliderRow({ label, value, min, max, step, suffix, onChange, ariaLabel, showInput = false }: SliderRowProps) {
  const displayValue = formatSliderValue(value);
  const handleInputChange = (nextValue: string) => {
    const parsed = Number.parseFloat(nextValue);
    if (!Number.isFinite(parsed)) return;
    onChange(clampToStep(parsed, min, max, step));
  };

  return (
    <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Slider
        aria-label={ariaLabel}
        aria-valuetext={`${displayValue}${suffix}`}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
      />
      {showInput ? (
        <div className="flex w-[72px] shrink-0 items-center gap-1">
          <Input
            aria-label={`${ariaLabel} value`}
            type="number"
            inputMode="decimal"
            min={min}
            max={max}
            step={step}
            value={displayValue}
            onChange={(event) => handleInputChange(event.target.value)}
            className="h-7 px-2 text-right text-xs tabular-nums"
          />
          <span className="text-xs text-muted-foreground">{suffix}</span>
        </div>
      ) : (
        <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
          {displayValue}{suffix}
        </span>
      )}
    </div>
  );
}

export const DEMEditorScene = memo(function DEMEditorScene({
  layer,
  onPaintChange,
  onStyleConfigChange,
  onOpacityChange,
  onZoomChange,
  onTerrainBind,
  onTerrainUnbind,
  terrainExaggeration,
  onTerrainExaggerationChange,
  onRemove,
  isTerrainBound = false,
}: DEMEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const mode = currentMode(layer);
  const paint = useMemo(() => layer.paint ?? {}, [layer.paint]);

  const layout = layer.layout ?? {};
  const minZoom = clampZoom(
    typeof layout._minzoom === 'number' ? layout._minzoom : 0,
  );
  const maxZoom = clampZoom(
    typeof layout._maxzoom === 'number' ? layout._maxzoom : 22,
  );

  const handleSwitchMode = useCallback((nextMode: DemRenderMode) => {
    const current = currentMode(layer);
    if (current === nextMode) return;

    const nextConfig: Record<string, unknown> = { ...(layer.style_config ?? {}) };
    nextConfig.render_mode = nextMode;

    // Source binding (the layer dataset_id + paint object) is intentionally preserved unchanged
    // across mode switches. Mode-specific paint values stay in layer.paint; reading the paint dict
    // per key (e.g. hillshade-* keys) returns last-saved values on re-entry.
    onStyleConfigChange(
      Object.keys(nextConfig).length > 0 ? (nextConfig as StyleConfig) : null,
      layer.paint ?? {},
    );

    if (nextMode === 'terrain') {
      onTerrainBind(layer.id);
    } else if (current === 'terrain') {
      onTerrainUnbind(layer.id);
    }
  }, [layer, onStyleConfigChange, onTerrainBind, onTerrainUnbind]);

  const handlePaintValue = useCallback((key: string, value: unknown) => {
    const nextValue = key === 'hillshade-exaggeration' && typeof value === 'number'
      ? normalizeHillshadeExaggeration(value)
      : value;
    onPaintChange({ ...paint, [key]: nextValue });
  }, [paint, onPaintChange]);

  const pills: { id: DemRenderMode; label: string }[] = [
    { id: 'hillshade', label: t('demEditor.renderAsHillshade', { defaultValue: '⛰ Hillshade' }) },
    { id: 'terrain', label: t('demEditor.renderAsTerrain', { defaultValue: '◬ Terrain' }) },
  ];

  // builder-audit #338 CONSIST-01: read hillshade fallbacks from the adapter's
  // HILLSHADE_PAINT_DEFAULTS (the values buildHillshadePaint actually renders) rather
  // than re-typing literals, so the editor swatch can never diverge from the rendered
  // default (the prior '#D4A97A' accent showed brown while the map painted black).
  const azimuth = getNumberPaint(paint, 'hillshade-illumination-direction', HILLSHADE_PAINT_DEFAULTS['hillshade-illumination-direction']);
  const exaggeration = normalizeHillshadeExaggeration(getNumberPaint(paint, 'hillshade-exaggeration', HILLSHADE_PAINT_DEFAULTS['hillshade-exaggeration']));
  const terrainSurfaceExaggeration = normalizeTerrainExaggeration(terrainExaggeration);

  const highlightColor = getStringPaint(paint, 'hillshade-highlight-color', HILLSHADE_PAINT_DEFAULTS['hillshade-highlight-color']);
  const shadowColor = getStringPaint(paint, 'hillshade-shadow-color', HILLSHADE_PAINT_DEFAULTS['hillshade-shadow-color']);
  const accentColor = getStringPaint(paint, 'hillshade-accent-color', HILLSHADE_PAINT_DEFAULTS['hillshade-accent-color']);

  const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity)
    ? layer.opacity
    : 1;

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* 1. RENDER AS section — always expanded */}
      <section
        aria-labelledby={`section-renderas-dem-${layer.id}`}
        className="border-b"
      >
        <div className="px-4 py-2">
          <p
            id={`section-renderas-dem-${layer.id}`}
            className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
          >
            {t('demEditor.renderAsLabel', { defaultValue: 'RENDER AS' })}
          </p>
          <div role="radiogroup" className="flex flex-wrap gap-1.5">
            {pills.map((pill) => {
              const isActive = mode === pill.id;
              return (
                <button
                  key={pill.id}
                  type="button"
                  role="radio"
                  aria-checked={isActive}
                  data-active={isActive ? 'true' : 'false'}
                  className={[
                    'rounded-full border border-transparent px-[10px] py-[5px] text-[12px] transition-colors',
                    isActive
                      ? 'bg-primary text-primary-foreground border-transparent'
                      : 'bg-[var(--surface-2,theme(colors.muted.DEFAULT))] text-foreground hover:bg-[var(--surface-3,theme(colors.muted.DEFAULT))]',
                  ].join(' ')}
                  onClick={() => {
                    if (!isActive) handleSwitchMode(pill.id);
                  }}
                >
                  {pill.label}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* 2. APPEARANCE section — content branches on mode */}
      <section
        aria-labelledby={`section-appearance-dem-${layer.id}`}
        className="border-b"
      >
        <div className="px-4 py-2">
          <p
            id={`section-appearance-dem-${layer.id}`}
            className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
          >
            {t('layerEditor.section.appearance', { defaultValue: 'Appearance' })}
          </p>

          {mode === 'hillshade' && (
            <div className="space-y-4">
              {/* builder-audit #338 YAGNI-01: advisory note when this DEM is also bound as the
                  map's 3D terrain source. Hillshade shading is hidden in that case to avoid
                  two raster-dem consumers on one source (a MapLibre error). The parent
                  computes isTerrainBound via isHillshadeTerrainBound. */}
              {isTerrainBound && (
                <p role="note" className="rounded-md bg-muted/50 px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
                  {t('demEditor.terrainBoundNote', {
                    defaultValue: "This DEM also powers the map's 3D terrain. Hillshade shading is hidden to avoid a source conflict.",
                  })}
                </p>
              )}

              {/* Sub-section: SUN POSITION */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-3">
                  {t('demEditor.sunPositionLabel', { defaultValue: 'SUN POSITION' })}
                </p>

                {/* builder-audit #338 COMPLEX-01: compass extracted to SunCompass. */}
                <SunCompass
                  azimuth={azimuth}
                  ariaLabel={t('demEditor.compassAriaLabel', {
                    azimuth,
                    defaultValue: 'Sun azimuth: {{azimuth}}°',
                  })}
                />

                {/* Sliders */}
                <div className="space-y-2">
                  <SliderRow
                    label={t('demEditor.azimuth', { defaultValue: 'Azimuth' })}
                    value={azimuth}
                    min={0}
                    max={360}
                    step={1}
                    suffix="°"
                    ariaLabel={t('demEditor.azimuth', { defaultValue: 'Azimuth' })}
                    onChange={(v) => handlePaintValue('hillshade-illumination-direction', v)}
                  />
                  <SliderRow
                    label={t('demEditor.exaggeration', { defaultValue: 'Exaggeration' })}
                    value={exaggeration}
                    min={HILLSHADE_EXAGGERATION_MIN}
                    max={HILLSHADE_EXAGGERATION_MAX}
                    step={0.1}
                    suffix="×"
                    ariaLabel={t('demEditor.exaggeration', { defaultValue: 'Exaggeration' })}
                    onChange={(v) => handlePaintValue('hillshade-exaggeration', normalizeHillshadeExaggeration(v))}
                  />
                </div>
              </div>

              {/* Sub-section: SHADING COLORS */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
                  {t('demEditor.shadingColorsLabel', { defaultValue: 'SHADING COLORS' })}
                </p>
                <div className="space-y-2">
                  <StyleColorPicker
                    label={t('demEditor.highlight', { defaultValue: 'Highlight' })}
                    color={highlightColor}
                    onChange={(v) => handlePaintValue('hillshade-highlight-color', v)}
                  />
                  <StyleColorPicker
                    label={t('demEditor.shadow', { defaultValue: 'Shadow' })}
                    color={shadowColor}
                    onChange={(v) => handlePaintValue('hillshade-shadow-color', v)}
                  />
                  <StyleColorPicker
                    label={t('demEditor.accent', { defaultValue: 'Accent' })}
                    color={accentColor}
                    onChange={(v) => handlePaintValue('hillshade-accent-color', v)}
                  />
                </div>
              </div>
            </div>
          )}

          {mode === 'terrain' && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                {t('demEditor.terrainHint', {
                  defaultValue:
                    'Terrain uses elevation data to extrude the map surface.',
                })}
              </p>
              <SliderRow
                label={t('demEditor.terrainExaggeration', { defaultValue: 'Exaggeration' })}
                value={terrainSurfaceExaggeration}
                min={TERRAIN_EXAGGERATION_MIN}
                max={TERRAIN_EXAGGERATION_MAX}
                step={0.1}
                suffix="×"
                ariaLabel={t('demEditor.terrainExaggeration', { defaultValue: 'Terrain exaggeration' })}
                onChange={(v) => onTerrainExaggerationChange(layer.id, normalizeTerrainExaggeration(v))}
                showInput
              />
            </div>
          )}
        </div>
      </section>

      {/* 3. HYPSOMETRIC TINT section — hillshade (full control) and terrain (hint only) modes */}
      <section
        aria-labelledby={`section-hypso-dem-${layer.id}`}
        className="border-b"
      >
        <div className="px-4 py-2">
          <p
            id={`section-hypso-dem-${layer.id}`}
            className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
          >
            {t('demEditor.sectionHypsometricTint', { defaultValue: 'HYPSOMETRIC TINT' })}
          </p>

          {/* Terrain mode: inline hint only — color-relief requires hillshade mode */}
          {mode === 'terrain' && (
            <p className="text-xs text-muted-foreground">
              {t('demEditor.hypsometricTerrainHint', {
                defaultValue: 'Elevation tint is not available in Terrain mode',
              })}
            </p>
          )}

          {/* Hillshade mode: full toggle + ramp picker */}
          {mode === 'hillshade' && (
            <div className="space-y-3">
              {/* Enable toggle */}
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground">
                  {t('demEditor.hypsometricEnable', { defaultValue: 'Elevation tint' })}
                </Label>
                <Switch
                  checked={paint['_hypso-enabled'] === true}
                  onCheckedChange={(next) => handlePaintValue('_hypso-enabled', next)}
                  aria-label={t('demEditor.hypsometricEnable', { defaultValue: 'Elevation tint' })}
                />
              </div>
              {/* Ramp picker — conditionally rendered (mount/unmount) when enabled */}
              {paint['_hypso-enabled'] === true && (
                <>
                  <ColorRampPicker
                    mode="graduated"
                    rampName={getStringPaint(paint, '_hypso-ramp', 'Viridis')}
                    onChange={(name) => handlePaintValue('_hypso-ramp', name)}
                  />
                  {/* builder-audit #338 MAINT-01: surface the hardcoded 0–4000 m, meters-only
                      elevation range limitation in-product (buildElevationExpression in
                      color-relief-sync.ts has no min/max control yet). */}
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    {t('demEditor.hypsometricRangeNote', {
                      defaultValue: 'Elevation tint spans 0–4000 m and assumes meters. DEMs in other units or ranges may appear flat.',
                    })}
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 4. VISIBILITY section — always expanded */}
      <section
        aria-labelledby={`section-visibility-dem-${layer.id}`}
        className="border-b"
      >
        <div className="px-4 py-2">
          <p
            id={`section-visibility-dem-${layer.id}`}
            className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
          >
            {t('layerEditor.section.visibility', { defaultValue: 'Visibility' })}
          </p>
          <div className="space-y-3">
            {/* Opacity slider */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                {t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
              </Label>
              <Slider
                aria-label={t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
                aria-valuetext={`${Math.round(opacity * 100)}%`}
                value={[opacity]}
                min={0}
                max={1}
                step={0.05}
                className="w-full"
                onValueChange={([value]) => {
                  onOpacityChange(Number((value ?? opacity).toFixed(2)));
                }}
              />
            </div>
            {/* Zoom range */}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label
                  htmlFor={`${layer.id}-dem-minzoom`}
                  className="text-xs text-muted-foreground"
                >
                  {t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                </Label>
                <Input
                  id={`${layer.id}-dem-minzoom`}
                  type="number"
                  min={0}
                  max={Math.max(0, maxZoom - 1)}
                  value={minZoom}
                  onChange={(e) => onZoomChange(clampZoom(Number(e.target.value)), maxZoom)}
                  className="h-8 text-xs"
                  aria-label={t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                />
              </div>
              <div className="space-y-1">
                <Label
                  htmlFor={`${layer.id}-dem-maxzoom`}
                  className="text-xs text-muted-foreground"
                >
                  {t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                </Label>
                <Input
                  id={`${layer.id}-dem-maxzoom`}
                  type="number"
                  min={Math.min(22, minZoom + 1)}
                  max={22}
                  value={maxZoom}
                  onChange={(e) => onZoomChange(minZoom, clampZoom(Number(e.target.value)))}
                  className="h-8 text-xs"
                  aria-label={t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer — Delete layer (inline confirmation, same pattern as FolderGroupRow) */}
      <footer className="shrink-0 border-t p-3 mt-auto">
        {!confirmDelete ? (
          <Button
            type="button"
            variant="ghost"
            className="w-full text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => setConfirmDelete(true)}
          >
            {t('layerEditor.deleteLayer', { defaultValue: 'Delete layer' })}
          </Button>
        ) : (
          <div role="alertdialog" aria-labelledby="dem-delete-confirm-title" className="space-y-2">
            <p id="dem-delete-confirm-title" className="text-sm text-destructive text-center">
              {t('layerEditor.deleteLayerConfirmMessage', { defaultValue: 'Delete this layer? This cannot be undone.' })}
            </p>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="destructive"
                className="flex-1"
                onClick={() => {
                  onRemove(layer.id);
                  setConfirmDelete(false);
                }}
              >
                {t('layerEditor.deleteLayerConfirmAction', { defaultValue: 'Delete' })}
              </Button>
              {/* autoFocus on the safe choice */}
              <Button
                type="button"
                variant="secondary"
                className="flex-1"
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
                onClick={() => setConfirmDelete(false)}
              >
                {t('layerEditor.deleteLayerConfirmCancel', { defaultValue: 'Keep layer' })}
              </Button>
            </div>
          </div>
        )}
      </footer>
    </div>
  );
});
