import { Circle, Minus, Pentagon } from 'lucide-react';
import { getColorProperty } from '@/lib/color-ramps';
import type { MapLayerResponse } from '@/types/api';

export function ColorizedGeometryIcon({
  geometryType,
  colors,
  layerId,
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
}) {
  const gt = (geometryType ?? '').toUpperCase();
  const isLine = gt.includes('LINE');
  const Icon = gt.includes('POINT') ? Circle : isLine ? Minus : Pentagon;

  if (colors.length <= 1) {
    const color = colors[0] ?? '#6366f1';
    return isLine
      ? <Icon className="h-3.5 w-3.5" stroke={color} strokeWidth={3} />
      : <Icon className="h-3.5 w-3.5" fill={color} strokeWidth={0} />;
  }

  const gradientId = `layer-grad-${layerId}`;
  return (
    <span className="relative inline-flex h-3.5 w-3.5">
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
      {isLine
        ? <Icon className="h-3.5 w-3.5" stroke={`url(#${gradientId})`} strokeWidth={3} />
        : <Icon className="h-3.5 w-3.5" fill={`url(#${gradientId})`} strokeWidth={0} />}
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
