import { memo, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { breakLabel } from '@/lib/legend-utils';
import { getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';

/* ── Shared swatch rendering ─────────────────────── */

interface SwatchStyle {
  outlineColor?: string;
  strokeDisabled?: boolean;
  opacity?: number;
}

function swatchStyle(color: string, s?: SwatchStyle): React.CSSProperties {
  return {
    backgroundColor: color,
    ...(!s?.strokeDisabled ? { borderColor: s?.outlineColor ?? MAP_COLORS.legendOutline } : {}),
    ...(s?.opacity !== undefined && s.opacity < 1 ? { opacity: s.opacity } : {}),
  };
}

function swatchClass(s?: SwatchStyle) {
  return cn('w-3.5 h-3.5 rounded-sm shrink-0', !s?.strokeDisabled && 'border');
}

/* ── Geometry-aware swatch ─────────────────────────── */

interface GeometrySwatchProps {
  geometryType?: string | null;
  color: string;
  style?: SwatchStyle;
}

export function GeometrySwatch({ geometryType, color, style: s }: GeometrySwatchProps) {
  const gt = (geometryType ?? '').toUpperCase();
  const opacityStyle: React.CSSProperties | undefined =
    s?.opacity !== undefined && s.opacity < 1 ? { opacity: s.opacity } : undefined;

  // Point: filled circle
  if (gt.includes('POINT')) {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className="shrink-0" style={opacityStyle} aria-hidden="true">
        <circle
          cx="7" cy="7" r="5"
          fill={color}
          stroke={s?.outlineColor ?? MAP_COLORS.legendOutline}
          strokeWidth={s?.strokeDisabled ? 0 : 1}
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

  // Polygon / default: filled rectangle (existing div-based swatch)
  return (
    <div
      className={swatchClass(s)}
      style={swatchStyle(color, s)}
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

export function CategoricalLegend({ categories, geometryType, style: s }: CategoricalLegendProps) {
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
}

/* ── Graduated color legend ──────────────────────── */

interface GraduatedColorLegendProps {
  colors: string[];
  breaks: number[];
  geometryType?: string | null;
  style?: SwatchStyle;
}

export function GraduatedColorLegend({ colors, breaks, geometryType, style: s }: GraduatedColorLegendProps) {
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
}

/* ── Graduated radius legend (SVG circles) ───────── */

interface GraduatedRadiusLegendProps {
  sizes: number[];
  breaks: number[];
  circleColor: string;
  colors?: string[];
  style?: SwatchStyle;
}

export function GraduatedRadiusLegend({ sizes, breaks, circleColor, colors, style: s }: GraduatedRadiusLegendProps) {
  return (
    <ul className="space-y-0.5">
      {sizes.map((size, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width="24" height="24" className="shrink-0" style={s?.opacity !== undefined && s.opacity < 1 ? { opacity: s.opacity } : undefined}>
            <circle
              cx="12" cy="12"
              r={Math.min(size, 12)}
              fill={colors?.[i] ?? circleColor} fillOpacity={0.8}
              stroke={s?.outlineColor ?? MAP_COLORS.legendOutline}
              strokeWidth={s?.strokeDisabled ? 0 : 1}
            />
          </svg>
          <span className="text-muted-foreground truncate">{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
}

/* ── Graduated width legend (SVG lines) ──────────── */

interface GraduatedWidthLegendProps {
  sizes: number[];
  breaks: number[];
  lineColor: string;
  style?: SwatchStyle;
}

export function GraduatedWidthLegend({ sizes, breaks, lineColor, style: s }: GraduatedWidthLegendProps) {
  return (
    <ul className="space-y-0.5">
      {sizes.map((size, i) => (
        <li key={i} className="flex items-center gap-1.5">
          <svg width="24" height="16" className="shrink-0" style={s?.opacity !== undefined && s.opacity < 1 ? { opacity: s.opacity } : undefined}>
            <line x1="0" y1="8" x2="24" y2="8" stroke={lineColor} strokeWidth={Math.min(size, 8)} strokeLinecap="round" />
          </svg>
          <span className="text-muted-foreground truncate">{breakLabel(i, breaks)}</span>
        </li>
      ))}
    </ul>
  );
}

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
