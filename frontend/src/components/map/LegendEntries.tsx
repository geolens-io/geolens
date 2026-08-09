import { memo, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { breakLabel } from '@/lib/legend-utils';
import { getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';

/* ── Shared swatch rendering ─────────────────────── */

export interface SwatchStyle {
  outlineColor?: string;
  strokeDisabled?: boolean;
  opacity?: number;
  fillOpacity?: number;
  strokeWidth?: number;
  /** fix(#951): paint['fill-pattern'] — the polygon chip draws the pattern, not a solid block. */
  fillPattern?: string;
  /**
   * fix(#914): the colour the MAP draws that pattern in, from fillPatternTint().
   * The chip's own `color` cannot be trusted for a patterned layer: a pattern
   * deletes fill-color from paint, so whatever derived that colour fell back to a
   * default while the map tints from the stash.
   */
  fillPatternColor?: string;
}

/**
 * Compute element-level opacity style from swatch style — LAYER opacity only.
 * fix(#1288): fillOpacity used to be folded in here and applied to the whole
 * swatch, so a stroke-only style (fill-opacity: 0) hid its own outline along
 * with the fill. fillOpacity is now applied per-element (SVG fill-opacity /
 * stroke-opacity, or an alpha-blended background) by each renderer below.
 */
function swatchOpacityStyle(s?: SwatchStyle): React.CSSProperties | undefined {
  const opacity = s?.opacity ?? 1;
  return opacity < 1 ? { opacity } : undefined;
}

/* ── Geometry-aware swatch ─────────────────────────── */

interface GeometrySwatchProps {
  geometryType?: string | null;
  color: string;
  style?: SwatchStyle;
}

export function GeometrySwatch({ geometryType, color, style: s }: GeometrySwatchProps) {
  const gt = (geometryType ?? '').toUpperCase();
  const opacityStyle = swatchOpacityStyle(s);

  // Point: filled circle
  if (gt.includes('POINT')) {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className="shrink-0" style={opacityStyle} aria-hidden="true">
        <circle
          cx="7" cy="7" r="5"
          fill={color}
          fillOpacity={s?.fillOpacity}
          stroke={s?.outlineColor ?? MAP_COLORS.legendOutline}
          strokeWidth={s?.strokeDisabled ? 0 : (s?.strokeWidth ?? 1)}
        />
      </svg>
    );
  }

  // Line: horizontal line segment
  if (gt.includes('LINE')) {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className="shrink-0" style={opacityStyle} aria-hidden="true">
        <line
          x1="1" y1="7" x2="13" y2="7"
          stroke={color}
          strokeOpacity={s?.fillOpacity}
          strokeWidth={2.5}
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // Polygon / default: filled rectangle — or the pattern preview when the layer
  // carries a fill-pattern, since MapLibre draws the pattern INSTEAD of the fill
  // (fix(#951): the chip used to show a solid block that appeared nowhere on the map).
  const borderColor = !s?.strokeDisabled ? (s?.outlineColor ?? MAP_COLORS.legendOutline) : undefined;
  const fillStyle: React.CSSProperties = s?.fillPattern
    ? {
        color: s.fillPatternColor ?? color,
        backgroundColor: 'transparent',
        ...patternPreviewStyle(s.fillPattern),
      }
    : { backgroundColor: color };
  // fix(#1288 codex): fillOpacity dims the fill LAYER only, rendered as a
  // nested element behind the border. Plain CSS opacity works for every CSS
  // color format (hex3/4/6/8, rgb()/hsl(), named colors) with no parsing, and
  // never touches the border, which must stay fully opaque for a stroke-only
  // style (fillOpacity 0) to remain visible.
  if (s?.fillOpacity !== undefined && s.fillOpacity < 1) {
    fillStyle.opacity = s.fillOpacity;
  }
  return (
    <div
      className={cn('relative w-3.5 h-3.5 rounded-sm shrink-0 overflow-hidden', !s?.strokeDisabled && 'border')}
      style={{
        ...(borderColor ? { borderColor } : {}),
        ...(s?.strokeWidth ? { borderWidth: s.strokeWidth } : {}),
        ...opacityStyle,
      }}
      aria-hidden="true"
    >
      <div className="absolute inset-0" style={fillStyle} />
    </div>
  );
}

/* ── Categorical legend ──────────────────────────── */

interface CategoricalLegendProps {
  categories: { value: string | number | null; label?: string; color: string }[];
  geometryType?: string | null;
  style?: SwatchStyle;
}

export const CategoricalLegend = memo(function CategoricalLegend({ categories, geometryType, style: s }: CategoricalLegendProps) {
  return (
    <ul className="space-y-0.5">
      {categories.map((cat, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <GeometrySwatch geometryType={geometryType} color={cat.color} style={s} />
          <span className="text-muted-foreground truncate">{cat.label ?? String(cat.value ?? 'null')}</span>
        </li>
      ))}
    </ul>
  );
});

/* ── Graduated color legend ──────────────────────── */

interface GraduatedColorLegendProps {
  colors: string[];
  breaks: number[];
  geometryType?: string | null;
  style?: SwatchStyle;
}

export const GraduatedColorLegend = memo(function GraduatedColorLegend({ colors, breaks, geometryType, style: s }: GraduatedColorLegendProps) {
  return (
    <ul className="space-y-0.5">
      {colors.map((color, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <GeometrySwatch geometryType={geometryType} color={color} style={s} />
          <span className="text-muted-foreground truncate">{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
});

/* ── Graduated radius legend (SVG circles) ───────── */

interface GraduatedRadiusLegendProps {
  sizes: number[];
  breaks: number[];
  circleColor: string;
  colors?: string[];
  style?: SwatchStyle;
}

export const GraduatedRadiusLegend = memo(function GraduatedRadiusLegend({ sizes, breaks, circleColor, colors, style: s }: GraduatedRadiusLegendProps) {
  const safeColors = colors?.length ? colors : undefined;
  const opacityStyle = swatchOpacityStyle(s);
  return (
    <ul className="space-y-0.5">
      {sizes.map((size, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="24" height="24" className="shrink-0" style={opacityStyle}>
            <circle
              cx="12" cy="12"
              r={Math.min(size, 12)}
              fill={safeColors?.[Math.min(i, safeColors.length - 1)] ?? circleColor}
              fillOpacity={s?.fillOpacity}
              stroke={s?.outlineColor ?? MAP_COLORS.legendOutline}
              strokeWidth={s?.strokeDisabled ? 0 : (s?.strokeWidth ?? 1)}
            />
          </svg>
          <span className="text-muted-foreground truncate">{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
});

/* ── Graduated width legend (SVG lines) ──────────── */

interface GraduatedWidthLegendProps {
  sizes: number[];
  breaks: number[];
  lineColor: string;
  style?: SwatchStyle;
}

export const GraduatedWidthLegend = memo(function GraduatedWidthLegend({ sizes, breaks, lineColor, style: s }: GraduatedWidthLegendProps) {
  const opacityStyle = swatchOpacityStyle(s);
  return (
    <ul className="space-y-0.5">
      {sizes.map((size, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg width="24" height="16" className="shrink-0" style={opacityStyle}>
            <line x1="0" y1="8" x2="24" y2="8" stroke={lineColor} strokeOpacity={s?.fillOpacity} strokeWidth={Math.min(size, 8)} strokeLinecap="round" />
          </svg>
          <span className="text-muted-foreground truncate">{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
});

/* ── Heatmap gradient legend ─────────────────────── */

interface HeatmapLegendProps {
  name: string;
  rampName: string;
  weightColumn?: string;
  opacity?: number;
  lowLabel: string;
  highLabel: string;
  weightedByLabel?: string;
}

export const HeatmapLegend = memo(function HeatmapLegend({
  name,
  rampName,
  weightColumn,
  opacity = 1,
  lowLabel,
  highLabel,
  weightedByLabel,
}: HeatmapLegendProps) {
  const gradient = useMemo(() => {
    const colors = getRampColors(rampName, 6);
    return `linear-gradient(to right, ${colors.join(', ')})`;
  }, [rampName]);

  return (
    <div style={opacity < 1 ? { opacity } : undefined}>
      {name && <div className="font-medium text-foreground mb-1 truncate">{name}</div>}
      <div
        className="h-3 rounded-sm w-full"
        style={{ background: gradient }}
      />
      <div className="flex justify-between mt-0.5">
        <span className="text-2xs text-muted-foreground">{lowLabel}</span>
        <span className="text-2xs text-muted-foreground">{highLabel}</span>
      </div>
      {weightColumn && weightedByLabel && (
        <div className="text-2xs text-muted-foreground mt-0.5 truncate">
          {weightedByLabel}
        </div>
      )}
    </div>
  );
});
