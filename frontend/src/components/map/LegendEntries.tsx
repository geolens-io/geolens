import { memo, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { breakLabel } from '@/lib/legend-utils';
import { getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';

/* ── Shared swatch rendering ─────────────────────── */

export interface SwatchStyle {
  outlineColor?: string;
  strokeDisabled?: boolean;
  opacity?: number;
  fillOpacity?: number;
  strokeWidth?: number;
}

/** Compute compound opacity style from swatch style. */
function swatchOpacityStyle(s?: SwatchStyle): React.CSSProperties | undefined {
  const compoundOpacity = (s?.opacity ?? 1) * (s?.fillOpacity ?? 1);
  return compoundOpacity < 1 ? { opacity: compoundOpacity } : undefined;
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
          strokeWidth={2.5}
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // Polygon / default: filled rectangle
  const borderColor = !s?.strokeDisabled ? (s?.outlineColor ?? MAP_COLORS.legendOutline) : undefined;
  const style: React.CSSProperties = {
    backgroundColor: color,
    ...(borderColor ? { borderColor } : {}),
    ...(s?.strokeWidth ? { borderWidth: s.strokeWidth } : {}),
    ...opacityStyle,
  };
  return (
    <div
      className={cn('w-3.5 h-3.5 rounded-sm shrink-0', !s?.strokeDisabled && 'border')}
      style={style}
      aria-hidden="true"
    />
  );
}

/* ── Categorical legend ──────────────────────────── */

interface CategoricalLegendProps {
  categories: { value: string; color: string }[];
  geometryType?: string | null;
  style?: SwatchStyle;
}

export const CategoricalLegend = memo(function CategoricalLegend({ categories, geometryType, style: s }: CategoricalLegendProps) {
  return (
    <ul className="space-y-0.5">
      {categories.map((cat, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <GeometrySwatch geometryType={geometryType} color={cat.color} style={s} />
          <span className="text-muted-foreground truncate">{cat.value}</span>
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
            <line x1="0" y1="8" x2="24" y2="8" stroke={lineColor} strokeWidth={Math.min(size, 8)} strokeLinecap="round" />
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
        <span className="text-[10px] text-muted-foreground">{lowLabel}</span>
        <span className="text-[10px] text-muted-foreground">{highLabel}</span>
      </div>
      {weightColumn && weightedByLabel && (
        <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
          {weightedByLabel}
        </div>
      )}
    </div>
  );
});
