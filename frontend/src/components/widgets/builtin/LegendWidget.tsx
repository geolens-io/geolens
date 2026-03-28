import { useTranslation } from 'react-i18next';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import { cn } from '@/lib/utils';
import type { WidgetContext } from '../types';

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
              {layer.style_config?.column ? (
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
                    layer.style_config.breaks &&
                    layer.style_config.colors && (
                      <ul className="space-y-0.5">
                        {layer.style_config.colors.map((color, i) => {
                          const breaks = layer.style_config!.breaks!;
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
