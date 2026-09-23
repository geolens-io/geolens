import { memo, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { breakLabel } from '@/lib/legend-utils';
import { getRampColors } from '@/lib/color-ramps';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';
import type { LegendSwatch } from './legend-facts';

/* ── Shared swatch rendering ─────────────────────── */

/**
 * Element-level opacity for the LAYER opacity only. Each renderer applies
 * fillOpacity to its fill alone, so a stroke-only style (fill-opacity: 0)
 * keeps its outline.
 */
function swatchOpacityStyle(s?: LegendSwatch | null): React.CSSProperties | undefined {
  const opacity = s?.opacity ?? 1;
  return opacity < 1 ? { opacity } : undefined;
}

/** SVG stroke attributes for a swatch's ring: none when the layer draws no stroke. */
function ringProps(s?: LegendSwatch | null) {
  return s?.stroke ? { stroke: s.stroke.color, strokeWidth: s.stroke.width } : { strokeWidth: 0 };
}

/* ── Geometry-aware swatch ─────────────────────────── */

interface GeometrySwatchProps {
  geometryType?: string | null;
  color: string;
  style?: LegendSwatch | null;
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
          {...ringProps(s)}
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

  // Polygon / default: filled rectangle, or the pattern preview when the layer
  // carries a fill-pattern, since MapLibre draws the pattern INSTEAD of the fill.
  const stroke = s?.stroke ?? null;
  const fillStyle: React.CSSProperties = s?.pattern
    ? {
        color: s.pattern.tint ?? color,
        backgroundColor: 'transparent',
        ...patternPreviewStyle(s.pattern.id),
      }
    : { backgroundColor: color };
  // fix(#1288 codex): fillOpacity dims the fill LAYER only, rendered as a
  // nested element behind the border. Plain CSS opacity works for every CSS
  // color format (hex3/4/6/8, rgb()/hsl(), named colors) with no parsing, and
  // never touches the border, which must stay fully opaque for a stroke-only
  // style (fillOpacity 0) to remain visible.
  if (s && s.fillOpacity < 1) {
    fillStyle.opacity = s.fillOpacity;
  }
  return (
    <div
      className={cn('relative w-3.5 h-3.5 rounded-sm shrink-0 overflow-hidden', stroke && 'border')}
      style={{
        ...(stroke ? { borderColor: stroke.color, borderWidth: stroke.width } : {}),
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
  style?: LegendSwatch | null;
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
  style?: LegendSwatch | null;
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
  style?: LegendSwatch | null;
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
              {...ringProps(s)}
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
  style?: LegendSwatch | null;
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
  reversed?: boolean;
  weightColumn?: string;
  opacity?: number;
  lowLabel: string;
  highLabel: string;
  weightedByLabel?: string;
}

export const HeatmapLegend = memo(function HeatmapLegend({
  name,
  rampName,
  reversed = false,
  weightColumn,
  opacity = 1,
  lowLabel,
  highLabel,
  weightedByLabel,
}: HeatmapLegendProps) {
  const gradient = useMemo(() => {
    const colors = getRampColors(rampName, 6, reversed);
    return `linear-gradient(to right, ${colors.join(', ')})`;
  }, [rampName, reversed]);

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
