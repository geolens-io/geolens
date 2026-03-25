import { Circle, Pentagon, Grid3x3, Layers } from 'lucide-react';
import { getColorProperty } from '@/lib/color-ramps';
import type { MapLayerResponse } from '@/types/api';

export interface StyleHints {
  strokeColor?: string;      // polygon _outline-color or circle-stroke-color
  dashPattern?: number[];    // line-dasharray from layout (e.g., [4,2])
  opacity?: number;          // layer opacity (0-1)
  strokeWidth?: number;      // line-width raw value — map to SVG strokeWidth
  radius?: number;           // circle-radius raw value — map to SVG size hint
}

/**
 * Extract style hints from paint/layout objects for icon rendering.
 * Reads custom conventions (_outline-color, line-dasharray in layout, etc.).
 */
export function extractStyleHints(
  paint: Record<string, unknown>,
  layout: Record<string, unknown>,
  geometryType: string | null,
  opacity?: number,
): StyleHints {
  const gt = (geometryType ?? '').toUpperCase();
  const hints: StyleHints = {};

  if (opacity !== undefined && opacity < 1) {
    hints.opacity = opacity;
  }

  if (gt.includes('LINE')) {
    const lw = paint['line-width'];
    if (typeof lw === 'number') hints.strokeWidth = lw;
    // line-dasharray is stored in layout in this codebase (see map-sync.ts)
    const dash = layout['line-dasharray'];
    if (Array.isArray(dash) && dash.length > 0) {
      hints.dashPattern = dash as number[];
    }
  } else if (gt.includes('POLYGON') || gt.includes('MULTI')) {
    const oc = paint['_outline-color'];
    if (typeof oc === 'string') hints.strokeColor = oc;
  }

  if (gt.includes('POINT')) {
    const sc = paint['circle-stroke-color'];
    if (typeof sc === 'string') hints.strokeColor = sc;
    const cr = paint['circle-radius'];
    if (typeof cr === 'number') hints.radius = cr;
  }

  return hints;
}

export function ColorizedGeometryIcon({
  geometryType,
  colors,
  layerId,
  layerType,
  styleHints,
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
  layerType?: string;
  styleHints?: StyleHints;
}) {
  // Raster/VRT layers use muted gray icons — no color tinting
  if (layerType === 'vrt') {
    return <Layers className="h-3.5 w-3.5 text-muted-foreground" />;
  }
  if (layerType === 'raster') {
    return <Grid3x3 className="h-3.5 w-3.5 text-muted-foreground" />;
  }

  const gt = (geometryType ?? '').toUpperCase();
  const isLine = gt.includes('LINE');
  const isPoint = gt.includes('POINT');

  const opacityStyle: React.CSSProperties | undefined =
    styleHints?.opacity !== undefined && styleHints.opacity < 1
      ? { opacity: styleHints.opacity }
      : undefined;

  // --- Line rendering ---
  if (isLine) {
    // Map strokeWidth to 3 tiers
    const rawSW = styleHints?.strokeWidth;
    const svgStrokeWidth = rawSW !== undefined
      ? (rawSW <= 1.5 ? 2 : rawSW > 4 ? 4.5 : 3)
      : 3;

    const color = colors[0] ?? '#6366f1';
    const hasGradient = colors.length > 1;
    const gradientId = `layer-grad-${layerId}`;

    // Scale dash values for the 14px icon
    const dashArray = styleHints?.dashPattern
      ? styleHints.dashPattern.map((v) => v * 1.5).join(' ')
      : undefined;

    const strokeColor = hasGradient ? `url(#${gradientId})` : color;

    return (
      <span className="relative inline-flex h-3.5 w-3.5 items-center justify-center" style={opacityStyle}>
        <svg width="14" height="14" viewBox="0 0 14 14" className="h-3.5 w-3.5">
          {hasGradient && (
            <defs>
              <linearGradient id={gradientId}>
                {colors.map((c, i) => (
                  <stop
                    key={i}
                    offset={`${(i / (colors.length - 1)) * 100}%`}
                    stopColor={c}
                  />
                ))}
              </linearGradient>
            </defs>
          )}
          <line
            x1="1"
            y1="7"
            x2="13"
            y2="7"
            stroke={strokeColor}
            strokeWidth={svgStrokeWidth}
            strokeLinecap="round"
            strokeDasharray={dashArray}
          />
        </svg>
      </span>
    );
  }

  // --- Circle radius → icon size ---
  let sizeClass = 'h-3.5 w-3.5';
  if (isPoint && styleHints?.radius !== undefined) {
    sizeClass = styleHints.radius <= 3
      ? 'h-2.5 w-2.5'
      : styleHints.radius > 7
        ? 'h-4.5 w-4.5'
        : 'h-3.5 w-3.5';
  }

  const Icon = isPoint ? Circle : Pentagon;

  // Single color
  if (colors.length <= 1) {
    const color = colors[0] ?? '#6366f1';

    if (isPoint && styleHints?.strokeColor) {
      return (
        <span style={opacityStyle} className="inline-flex">
          <Icon className={sizeClass} fill={color} stroke={styleHints.strokeColor} strokeWidth={1.5} />
        </span>
      );
    }

    // Polygon with outline color
    if (!isPoint && styleHints?.strokeColor) {
      return (
        <span style={opacityStyle} className="inline-flex">
          <Icon className={sizeClass} fill={color} stroke={styleHints.strokeColor} strokeWidth={1.5} />
        </span>
      );
    }

    return (
      <span style={opacityStyle} className="inline-flex">
        <Icon className={sizeClass} fill={color} strokeWidth={0} />
      </span>
    );
  }

  // Multi-color gradient
  const gradientId = `layer-grad-${layerId}`;
  return (
    <span className="relative inline-flex" style={opacityStyle}>
      <span className={`relative inline-flex ${sizeClass}`}>
        <svg width="0" height="0" className="absolute">
          <defs>
            <linearGradient id={gradientId}>
              {colors.map((c, i) => (
                <stop
                  key={i}
                  offset={`${(i / (colors.length - 1)) * 100}%`}
                  stopColor={c}
                />
              ))}
            </linearGradient>
          </defs>
        </svg>
        {styleHints?.strokeColor ? (
          <Icon className={sizeClass} fill={`url(#${gradientId})`} stroke={styleHints.strokeColor} strokeWidth={1.5} />
        ) : (
          <Icon className={sizeClass} fill={`url(#${gradientId})`} strokeWidth={0} />
        )}
      </span>
    </span>
  );
}

export function getLayerColors(layer: Pick<MapLayerResponse, 'dataset_geometry_type' | 'paint' | 'style_config'>): string[] {
  const colorKey = getColorProperty(layer.dataset_geometry_type);
  const value = layer.paint?.[colorKey];
  if (typeof value === 'string') return [value];
  if (layer.style_config?.categories?.length)
    return layer.style_config.categories.map((c) => c.color);
  if (layer.style_config?.colors?.length)
    return layer.style_config.colors;
  return ['#6366f1'];
}
