import { memo, useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { StyleColorPicker } from './StyleColorPicker';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

/**
 * DEM render mode union.
 * Note: 'terrain' is not currently in StyleConfig.render_mode union (which has
 * 'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster'). We cast at the boundary
 * to avoid a global type change. BSR-09 follow-up (Phase 1038 or backend change)
 * should extend the union to include 'terrain'.
 */
export type DemRenderMode = 'image' | 'hillshade' | 'terrain';

export interface DEMEditorSceneProps {
  layer: MapLayerResponse;
  // Render mode is derived from layer.style_config.render_mode by the component
  // (image when null/undefined or any non-DEM value)
  onPaintChange: (paint: Record<string, unknown>) => void;
  onStyleConfigChange: (config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onOpacityChange: (opacity: number) => void;
  onZoomChange: (min: number, max: number) => void;
  /** Called when the user switches to Terrain mode. Wires map-level terrain_config
   * via use-builder-layers handleDEMTerrainBind. */
  onTerrainBind: (layerId: string) => void;
  /** Called after the user confirms deletion. Matches the onRemove pattern in
   * LayerEditorHandlers — same wiring used by the default layer editor. */
  onRemove: (layerId: string) => void;
}

function currentMode(layer: MapLayerResponse): DemRenderMode {
  const m = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode;
  if (m === 'hillshade') return 'hillshade';
  if (m === 'terrain') return 'terrain';
  return 'image';
}

function getNumber(paint: Record<string, unknown>, key: string, fallback: number): number {
  return typeof paint[key] === 'number' ? (paint[key] as number) : fallback;
}

function getString(paint: Record<string, unknown>, key: string, fallback: string): string {
  return typeof paint[key] === 'string' ? (paint[key] as string) : fallback;
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
}

function SliderRow({ label, value, min, max, step, suffix, onChange, ariaLabel }: SliderRowProps) {
  return (
    <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Slider
        aria-label={ariaLabel}
        aria-valuetext={`${value}${suffix}`}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
      />
      <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
        {value}{suffix}
      </span>
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
  onRemove,
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
    if (nextMode === 'image') {
      delete nextConfig.render_mode;
    } else {
      nextConfig.render_mode = nextMode;
    }

    // Source binding (the layer dataset_id + paint object) is intentionally preserved unchanged
    // across mode switches. Mode-specific paint values stay in layer.paint; reading the paint dict
    // per key (e.g. hillshade-* keys) returns last-saved values on re-entry.
    onStyleConfigChange(
      Object.keys(nextConfig).length > 0 ? (nextConfig as StyleConfig) : null,
      layer.paint ?? {},
    );

    if (nextMode === 'terrain') {
      onTerrainBind(layer.id);
    }
  }, [layer, onStyleConfigChange, onTerrainBind]);

  const handlePaintValue = useCallback((key: string, value: unknown) => {
    onPaintChange({ ...paint, [key]: value });
  }, [paint, onPaintChange]);

  const pills: { id: DemRenderMode; label: string }[] = [
    { id: 'image', label: t('demEditor.renderAsImage', { defaultValue: '▦ Image' }) },
    { id: 'hillshade', label: t('demEditor.renderAsHillshade', { defaultValue: '⛰ Hillshade' }) },
    { id: 'terrain', label: t('demEditor.renderAsTerrain', { defaultValue: '◬ Terrain' }) },
  ];

  const azimuth = getNumber(paint, 'hillshade-illumination-direction', 335);
  // "_dem-sun-altitude" is a builder-side custom key with no MapLibre effect.
  // It persists user intent via the existing paint dict round-trip.
  // If a future MapLibre release adds altitude support, swap this key.
  const altitude = getNumber(paint, '_dem-sun-altitude', 45);
  const exaggeration = getNumber(paint, 'hillshade-exaggeration', 0.5);

  const highlightColor = getString(paint, 'hillshade-highlight-color', '#FFFFFF');
  const shadowColor = getString(paint, 'hillshade-shadow-color', '#000000');
  const accentColor = getString(paint, 'hillshade-accent-color', '#D4A97A');

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

          {mode === 'image' && (
            <p className="text-xs text-muted-foreground">
              {t('demEditor.imageHint', { defaultValue: 'No additional appearance controls for image mode' })}
            </p>
          )}

          {mode === 'hillshade' && (
            <div className="space-y-4">
              {/* Sub-section: SUN POSITION */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-3">
                  {t('demEditor.sunPositionLabel', { defaultValue: 'SUN POSITION' })}
                </p>

                {/* Compass widget — 90×90 circular card */}
                <div
                  role="img"
                  aria-label={t('demEditor.compassAriaLabel', {
                    azimuth,
                    defaultValue: 'Sun azimuth: {{azimuth}}°',
                  })}
                  className="relative mx-auto mb-3"
                  style={{
                    width: '90px',
                    height: '90px',
                    borderRadius: '50%',
                    border: '1px solid var(--border)',
                    background: 'radial-gradient(circle, var(--surface-1), var(--surface-2))',
                  }}
                >
                  {/* N-S crosshair */}
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      top: 0,
                      bottom: 0,
                      width: '1px',
                      background: 'var(--border)',
                      transform: 'translateX(-50%)',
                    }}
                  />
                  {/* E-W crosshair */}
                  <div
                    style={{
                      position: 'absolute',
                      top: '50%',
                      left: 0,
                      right: 0,
                      height: '1px',
                      background: 'var(--border)',
                      transform: 'translateY(-50%)',
                    }}
                  />
                  {/* Needle */}
                  <div
                    aria-hidden="true"
                    style={{
                      position: 'absolute',
                      left: '50%',
                      top: '50%',
                      width: '2px',
                      height: '38px',
                      background: 'var(--primary)',
                      transformOrigin: 'center bottom',
                      transform: `translate(-50%, -100%) rotate(${azimuth}deg)`,
                      borderRadius: '1px',
                    }}
                  />
                </div>

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
                    label={t('demEditor.altitude', { defaultValue: 'Altitude' })}
                    value={altitude}
                    min={0}
                    max={90}
                    step={1}
                    suffix="°"
                    ariaLabel={t('demEditor.altitude', { defaultValue: 'Altitude' })}
                    onChange={(v) => handlePaintValue('_dem-sun-altitude', v)}
                  />
                  <SliderRow
                    label={t('demEditor.exaggeration', { defaultValue: 'Exaggeration' })}
                    value={exaggeration}
                    min={0}
                    max={5}
                    step={0.1}
                    suffix="×"
                    ariaLabel={t('demEditor.exaggeration', { defaultValue: 'Exaggeration' })}
                    onChange={(v) => handlePaintValue('hillshade-exaggeration', v)}
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
            <p className="text-xs text-muted-foreground">
              {t('demEditor.terrainHint', {
                defaultValue:
                  'Terrain uses elevation data to extrude the map surface. Adjust terrain exaggeration in Settings → Terrain.',
              })}
            </p>
          )}
        </div>
      </section>

      {/* 3. VISIBILITY section — always expanded */}
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
