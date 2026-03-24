import type { StyleConfig } from '@/types/api';
import { ColorizedGeometryIcon, getLayerColors } from './layer-icons';

interface MapLegendLayer {
  name: string;
  styleConfig?: StyleConfig | null;
  visible: boolean;
  show_in_legend?: boolean;
  geometryType?: string | null;
  paint?: Record<string, unknown>;
  layerType?: string;
}

interface MapLegendProps {
  layers: MapLegendLayer[];
}

export function MapLegend({ layers }: MapLegendProps) {
  const legendLayers = layers.filter((l) => l.visible && l.show_in_legend !== false);

  if (legendLayers.length === 0) return null;

  return (
    <div className="absolute bottom-4 left-4 z-10 bg-card rounded-lg shadow-md border max-w-56 max-h-64 overflow-y-auto">
      {legendLayers.map((layer, idx) => (
        <div key={idx} className="p-2.5 text-xs">
          {layer.styleConfig?.column ? (
            <>
              <div className="font-medium text-foreground mb-1.5 truncate">{layer.name}</div>

              {layer.styleConfig?.mode === 'categorical' && layer.styleConfig.categories && (
                <ul className="space-y-0.5">
                  {layer.styleConfig.categories.map((cat, i) => (
                    <li key={i} className="flex items-center gap-1.5">
                      <div
                        className="w-3 h-3 rounded-sm shrink-0"
                        style={{ backgroundColor: cat.color }}
                      />
                      <span className="text-muted-foreground truncate">{cat.value}</span>
                    </li>
                  ))}
                </ul>
              )}

              {layer.styleConfig?.mode === 'graduated' &&
                layer.styleConfig.breaks &&
                layer.styleConfig.colors && (
                  <ul className="space-y-0.5">
                    {layer.styleConfig.colors.map((color, i) => {
                      const breaks = layer.styleConfig!.breaks!;
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
                            className="w-3 h-3 rounded-sm shrink-0"
                            style={{ backgroundColor: color }}
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
                geometryType={layer.geometryType ?? null}
                colors={getLayerColors({
                  dataset_geometry_type: layer.geometryType ?? null,
                  paint: layer.paint ?? {},
                  style_config: layer.styleConfig,
                })}
                layerId={`legend-${idx}`}
              />
              <span className="font-medium text-foreground truncate">{layer.name}</span>
            </div>
          )}

          {idx < legendLayers.length - 1 && (
            <div className="border-b mt-2" />
          )}
        </div>
      ))}
    </div>
  );
}
