import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

/**
 * RasterStretchControls — the shared COLORMAP / STRETCH section for raster layers.
 *
 * Single source of truth used by BOTH raster editors:
 *  - `RasterLayerControls` (the editor LayerEditorPanel actually mounts for raster/vrt layers)
 *  - `LayerStyleEditor/RasterEditor` (mounted via RenderModeSwitch for non-raster paths)
 *
 * Gate-split:
 *  - STRETCH:  visible for any numeric band_count >= 1 (single AND multi-band) — RASTER-STRETCH-03
 *  - COLORMAP: single-band only (band_count === 1) — RASTER-STRETCH-UI / v1031
 *  - HINT:     single-band only, when stretch != minmax AND colormap != gray — RASTER-STRETCH-UI-02
 *
 * `_colormap` / `_stretch` / `_pmin` / `_pmax` / `_sigma` are builder-private paint keys.
 * They mutate the tile URL via buildColormapTileUrl (map-sync.ts) and never reach
 * MapLibre setPaintProperty (intentionally absent from RASTER_OWNED_PAINT_PROPERTIES).
 *
 * Not shown for DEM layers — stretch corrupts terrainrgb encoding and the backend
 * short-circuits stretch for is_dem rasters.
 */
export interface RasterStretchControlsProps {
  /** Numeric band count from the resolved layer; section hides when absent/<1. */
  bandCount: number | null | undefined;
  /** Merged builder paint dict (reads the builder-private `_*` keys). */
  paint: Record<string, unknown>;
  /** Patch a single builder-private paint key. */
  onPaintProp: (key: string, value: unknown) => void;
  /** DEM layers never show stretch/colormap (terrainrgb). */
  isDem?: boolean | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function RasterStretchControls({
  bandCount,
  paint,
  onPaintProp,
  isDem = false,
  t,
}: RasterStretchControlsProps) {
  if (isDem) return null;
  if (typeof bandCount !== 'number' || bandCount < 1) return null;

  const isSingleBand = bandCount === 1;
  const currentStretch = String(paint['_stretch'] ?? 'minmax');
  const currentColormap = String(paint['_colormap'] ?? 'gray');
  const pmin = typeof paint['_pmin'] === 'number' ? (paint['_pmin'] as number) : 2;
  const pmax = typeof paint['_pmax'] === 'number' ? (paint['_pmax'] as number) : 98;
  const sigma = typeof paint['_sigma'] === 'number' ? (paint['_sigma'] as number) : 2;

  const handlePminChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // Number('') is 0 → would silently write pmin=0 on backspace. Ignore empty/non-finite.
    const raw = e.target.value;
    if (raw === '') return;
    const candidate = Number(raw);
    if (Number.isFinite(candidate) && candidate >= 0 && candidate < pmax) {
      onPaintProp('_pmin', candidate);
    }
  };

  const handlePmaxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value;
    if (raw === '') return;
    const candidate = Number(raw);
    if (Number.isFinite(candidate) && candidate > pmin && candidate <= 100) {
      onPaintProp('_pmax', candidate);
    }
  };

  return (
    <section className="border-b">
      <div className="px-4 py-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
          {isSingleBand
            ? t('style.raster.sectionColormap', { defaultValue: 'COLORMAP' })
            : t('style.raster.stretchLabel', { defaultValue: 'STRETCH' })}
        </p>
        <div className="space-y-3">
          {/* Colormap select row — single-band only */}
          {isSingleBand && (
            <div className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-xs text-muted-foreground">
                {t('style.raster.colormapLabel', { defaultValue: 'Colormap' })}
              </span>
              {/* builder-audit DUP-03: these 8 colormap values are hand-mirrored against the
                  backend validator _ALLOWED_COLORMAPS (backend/app/processing/tiles/router.py:459-461),
                  which 422s anything not in that frozenset. There is no codegen guard — adding or
                  renaming a colormap on either side must be mirrored here (and vice-versa). */}
              <Select value={currentColormap} onValueChange={(v) => onPaintProp('_colormap', v)}>
                <SelectTrigger className="h-8 text-xs flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gray">{t('style.raster.colormapGray', { defaultValue: 'Grayscale' })}</SelectItem>
                  <SelectItem value="viridis">{t('style.raster.colormapViridis', { defaultValue: 'Viridis' })}</SelectItem>
                  <SelectItem value="inferno">{t('style.raster.colormapInferno', { defaultValue: 'Inferno' })}</SelectItem>
                  <SelectItem value="plasma">{t('style.raster.colormapPlasma', { defaultValue: 'Plasma' })}</SelectItem>
                  <SelectItem value="magma">{t('style.raster.colormapMagma', { defaultValue: 'Magma' })}</SelectItem>
                  <SelectItem value="ylorrd">{t('style.raster.colormapYlorrd', { defaultValue: 'Yellow-Red' })}</SelectItem>
                  <SelectItem value="bugn">{t('style.raster.colormapBugn', { defaultValue: 'Blue-Green' })}</SelectItem>
                  <SelectItem value="terrain">{t('style.raster.colormapTerrain', { defaultValue: 'Terrain' })}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Stretch select row — minmax / percentile (p2–p98) / stddev (mean±2σ).
              percentile and stddev compute a stats-based rescale via the raster-proxy →
              Titiler /cog/statistics. Visible for all band_count >= 1 (RASTER-STRETCH-03). */}
          <div className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">
              {t('style.raster.stretchLabel', { defaultValue: 'Stretch' })}
            </span>
            <Select value={currentStretch} onValueChange={(v) => onPaintProp('_stretch', v)}>
              <SelectTrigger className="h-8 text-xs flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="minmax">{t('style.raster.stretchMinmax', { defaultValue: 'Min/Max' })}</SelectItem>
                <SelectItem value="percentile">{t('style.raster.stretchPercentile', { defaultValue: 'Percentile' })}</SelectItem>
                <SelectItem value="stddev">{t('style.raster.stretchStddev', { defaultValue: 'Std Deviation' })}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Percentile bounds (RASTER-STRETCH-UI-01) — pmin/pmax inputs */}
          {currentStretch === 'percentile' && (
            <div className="flex gap-2">
              <div className="flex-1 flex flex-col gap-1">
                <Label className="text-xs text-muted-foreground">{t('style.raster.pminLabel', { defaultValue: 'Low %' })}</Label>
                <input
                  type="number"
                  className="h-8 text-xs w-full rounded-md border border-input bg-background px-2"
                  min={0}
                  max={100}
                  step={1}
                  value={pmin}
                  onChange={handlePminChange}
                />
              </div>
              <div className="flex-1 flex flex-col gap-1">
                <Label className="text-xs text-muted-foreground">{t('style.raster.pmaxLabel', { defaultValue: 'High %' })}</Label>
                <input
                  type="number"
                  className="h-8 text-xs w-full rounded-md border border-input bg-background px-2"
                  min={0}
                  max={100}
                  step={1}
                  value={pmax}
                  onChange={handlePmaxChange}
                />
              </div>
            </div>
          )}

          {/* Sigma segmented control (RASTER-STRETCH-UI-01) — 1/2/3 */}
          {currentStretch === 'stddev' && (
            <div className="flex items-center gap-2">
              <Label className="w-28 shrink-0 text-xs text-muted-foreground">
                {t('style.raster.sigmaLabel', { defaultValue: 'Sigma (σ)' })}
              </Label>
              <div className="flex gap-1">
                {([1, 2, 3] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={sigma === v}
                    className={cn(
                      'h-8 w-8 text-xs rounded-md border',
                      sigma === v
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background text-foreground border-input hover:bg-muted',
                    )}
                    onClick={() => onPaintProp('_sigma', v)}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Stretch↔colormap hint (RASTER-STRETCH-UI-02) — single-band only,
              shown when stretch is not minmax AND colormap is not gray */}
          {isSingleBand && currentStretch !== 'minmax' && currentColormap !== 'gray' && (
            <p role="note" className="text-[11px] leading-snug text-muted-foreground">
              {t('style.raster.stretchColormapHint', { defaultValue: 'Stretch sets the input range for the colormap.' })}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
