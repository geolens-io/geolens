import { useTranslation } from 'react-i18next';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import { getRampColors } from '@/lib/color-ramps';
import { cn } from '@/lib/utils';
import type { WidgetContext } from '../types';

function breakLabel(i: number, breaks: number[]): string {
  if (i === 0) return `< ${breaks[0]}`;
  if (i === breaks.length) return `>= ${breaks[breaks.length - 1]}`;
  return `${breaks[i - 1]} - ${breaks[i]}`;
}

export function LegendWidget({ ctx }: { ctx: WidgetContext }) {
  const { t } = useTranslation('builder');

  const legendLayers = ctx.layers.filter((l) => l.visible && l.show_in_legend !== false);

  if (legendLayers.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">{t('widgets.legend.noLayers')}</p>
    );
  }

  return (
    <div className="space-y-0 min-w-44">
      {legendLayers.map((layer, idx) => {
        const outlineColor = layer.paint?.['_outline-color'] as string | undefined;
        const strokeDisabled = !!layer.paint?.['_stroke-disabled'];
        const opacity = layer.opacity ?? 1;

        return (
          <div key={layer.id}>
            <div className="p-1 text-xs">
              {(layer.style_config as Record<string, unknown> | undefined)?.render_mode === 'heatmap' ? (
                <HeatmapLegend
                  name={layer.display_name ?? layer.dataset_name}
                  rampName={(layer.paint?.['_heatmap-ramp'] as string) ?? 'YlOrRd'}
                  weightColumn={(layer.paint?.['_heatmap-weight-column'] as string) ?? undefined}
                  opacity={opacity}
                />
              ) : layer.style_config?.column ? (
                <>
                  <div className="font-medium text-foreground mb-1 truncate">
                    {layer.display_name ?? layer.dataset_name}
                  </div>

                  {layer.style_config.mode === 'categorical' && layer.style_config.categories && (
                    <ul className="space-y-0.5">
                      {layer.style_config.categories.map((cat, i) => (
                        <li key={i} className="flex items-center gap-1.5">
                          <div
                            className={cn('w-3 h-3 rounded-sm shrink-0', !strokeDisabled && 'border')}
                            style={{
                              backgroundColor: cat.color,
                              ...(!strokeDisabled ? { borderColor: outlineColor ?? 'rgba(0,0,0,0.2)' } : {}),
                              ...(opacity < 1 ? { opacity } : {}),
                            }}
                          />
                          <span className="text-muted-foreground truncate">{cat.value}</span>
                        </li>
                      ))}
                    </ul>
                  )}

                  {layer.style_config.mode === 'graduated' &&
                    layer.style_config.breaks && (
                      (() => {
                        const sc = layer.style_config;
                        const breaks = sc.breaks!;
                        const target = sc.target;

                        // Size legend for radius (proportional circles)
                        if (target === 'radius' && sc.sizes) {
                          const circleColor = (layer.paint?.['circle-color'] as string | undefined) ?? '#888';
                          return (
                            <ul className="space-y-0.5">
                              {sc.sizes.map((size, i) => {
                                const label = breakLabel(i, breaks);
                                const r = Math.min(size, 12);
                                return (
                                  <li key={i} className="flex items-center gap-1.5">
                                    <svg
                                      viewBox="0 0 24 24"
                                      width="24"
                                      height="24"
                                      className="shrink-0"
                                      style={{ opacity: opacity < 1 ? opacity : undefined }}
                                    >
                                      <circle
                                        cx="12"
                                        cy="12"
                                        r={r}
                                        fill={circleColor}
                                        fillOpacity={0.8}
                                        stroke={outlineColor ?? 'rgba(0,0,0,0.2)'}
                                        strokeWidth={strokeDisabled ? 0 : 1}
                                      />
                                    </svg>
                                    <span className="text-muted-foreground truncate">{label}</span>
                                  </li>
                                );
                              })}
                            </ul>
                          );
                        }

                        // Size legend for width (weighted lines)
                        if (target === 'width' && sc.sizes) {
                          const lineColor = (layer.paint?.['line-color'] as string | undefined) ?? '#888';
                          return (
                            <ul className="space-y-0.5">
                              {sc.sizes.map((size, i) => {
                                const label = breakLabel(i, breaks);
                                const sw = Math.min(size, 8);
                                return (
                                  <li key={i} className="flex items-center gap-1.5">
                                    <svg
                                      width="24"
                                      height="16"
                                      className="shrink-0"
                                      style={{ opacity: opacity < 1 ? opacity : undefined }}
                                    >
                                      <line
                                        x1="0"
                                        y1="8"
                                        x2="24"
                                        y2="8"
                                        stroke={lineColor}
                                        strokeWidth={sw}
                                        strokeLinecap="round"
                                      />
                                    </svg>
                                    <span className="text-muted-foreground truncate">{label}</span>
                                  </li>
                                );
                              })}
                            </ul>
                          );
                        }

                        // Default: color legend (target === 'color' or no target)
                        if (!sc.colors) return null;
                        return (
                          <ul className="space-y-0.5">
                            {sc.colors.map((color, i) => {
                              let label: string;
                              if (i === 0) {
                                label = `< ${breaks[0]}`;
                              } else if (i === breaks.length) {
                                label = `>= ${breaks[breaks.length - 1]}`;
                              } else {
                                label = `${breaks[i - 1]} - ${breaks[i]}`;
                              }
                              return (
                                <li key={i} className="flex items-center gap-1.5">
                                  <div
                                    className={cn('w-3 h-3 rounded-sm shrink-0', !strokeDisabled && 'border')}
                                    style={{
                                      backgroundColor: color,
                                      ...(!strokeDisabled ? { borderColor: outlineColor ?? 'rgba(0,0,0,0.2)' } : {}),
                                      ...(opacity < 1 ? { opacity } : {}),
                                    }}
                                  />
                                  <span className="text-muted-foreground truncate">{label}</span>
                                </li>
                              );
                            })}
                          </ul>
                        );
                      })()
                    )}
                </>
              ) : (
                <div className="flex items-center gap-1.5">
                  <ColorizedGeometryIcon
                    geometryType={layer.dataset_geometry_type ?? null}
                    colors={getLayerColors({
                      dataset_geometry_type: layer.dataset_geometry_type ?? null,
                      paint: layer.paint ?? {},
                      style_config: layer.style_config,
                    })}
                    layerId={`legend-widget-${idx}`}
                    layerType={layer.layer_type ?? undefined}
                    styleHints={extractStyleHints(
                      layer.paint ?? {},
                      layer.layout ?? {},
                      layer.dataset_geometry_type ?? null,
                      opacity,
                    )}
                  />
                  <span className="font-medium text-foreground truncate">
                    {layer.display_name ?? layer.dataset_name}
                  </span>
                </div>
              )}
            </div>
            {idx < legendLayers.length - 1 && <div className="border-b" />}
          </div>
        );
      })}
    </div>
  );
}

function HeatmapLegend({
  name,
  rampName,
  weightColumn,
  opacity,
}: {
  name: string;
  rampName: string;
  weightColumn?: string;
  opacity: number;
}) {
  const { t } = useTranslation('builder');
  const colors = getRampColors(rampName, 6);
  const gradient = `linear-gradient(to right, ${colors.join(', ')})`;

  return (
    <div style={opacity < 1 ? { opacity } : undefined}>
      <div className="font-medium text-foreground mb-1 truncate">{name}</div>
      <div
        className="h-3 rounded-sm w-full"
        style={{ background: gradient }}
      />
      <div className="flex justify-between mt-0.5">
        <span className="text-[10px] text-muted-foreground">{t('widgets.legend.low')}</span>
        <span className="text-[10px] text-muted-foreground">{t('widgets.legend.high')}</span>
      </div>
      {weightColumn && (
        <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
          {t('widgets.legend.weightedBy', { column: weightColumn })}
        </div>
      )}
    </div>
  );
}
