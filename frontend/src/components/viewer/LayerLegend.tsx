import type { SharedLayerResponse } from '@/types/api';
import { useTranslation } from 'react-i18next';
import { MAP_COLORS } from '@/lib/map-colors';
import { Eye, EyeOff, Layers, X } from 'lucide-react';
import { getGeometryFamilyLabel } from '@/i18n/labels';

interface LayerLegendProps {
  layers: SharedLayerResponse[];
  visibleLayers: Set<number>;
  onToggleVisibility: (sortOrder: number) => void;
  isOpen: boolean;
  onToggle: () => void;
}

function getSwatchColor(layer: SharedLayerResponse): string {
  const paint = layer.paint as Record<string, unknown>;
  if (!paint) return MAP_COLORS.default.fill;

  const gt = (layer.geometry_type ?? '').toUpperCase();
  let colorVal: unknown;
  if (gt.includes('POINT')) colorVal = paint['circle-color'];
  else if (gt.includes('LINE')) colorVal = paint['line-color'];
  else colorVal = paint['fill-color'];

  // If data-driven (expression array), return fallback
  if (Array.isArray(colorVal)) return MAP_COLORS.default.fill;
  return (colorVal as string) ?? MAP_COLORS.default.fill;
}

export function LayerLegend({
  layers,
  visibleLayers,
  onToggleVisibility,
  isOpen,
  onToggle,
}: LayerLegendProps) {
  const { t } = useTranslation('common');
  const sorted = [...layers]
    .filter((l) => l.show_in_legend !== false)
    .sort((a, b) => a.sort_order - b.sort_order);

  return (
    <>
      {/* Toggle button — always visible */}
      <button
        type="button"
        onClick={onToggle}
        className="absolute left-3 top-3 z-20 flex items-center justify-center w-8 h-8 rounded-md bg-background/80 backdrop-blur-sm border border-border/50 shadow-sm text-foreground hover:bg-background transition-colors"
        title={isOpen ? t('viewer.legend.hide') : t('viewer.legend.show')}
      >
        {isOpen ? <X className="w-4 h-4" /> : <Layers className="w-4 h-4" />}
      </button>

      {/* Legend panel — shown when open */}
      <div
        className={`absolute left-3 top-14 z-10 w-56 max-h-[calc(100vh-5rem)] overflow-y-auto bg-background/90 backdrop-blur-md rounded-lg shadow-lg border border-border/50 transition-all duration-200 ${
          isOpen
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 -translate-y-2 pointer-events-none'
        }`}
      >
        <div className="p-3 border-b border-border/50">
          <h3 className="text-sm font-semibold text-foreground">{t('viewer.legend.title')}</h3>
        </div>
        <ul className="divide-y divide-border/50">
          {sorted.map((layer) => {
            const isVisible = visibleLayers.has(layer.sort_order);
            const color = getSwatchColor(layer);
            const sc = layer.style_config;
            return (
              <li key={layer.sort_order} className="px-3 py-2 hover:bg-accent/50">
                <div className="flex items-center gap-2">
                  <div
                    className="w-4 h-4 rounded-sm flex-shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-xs text-muted-foreground flex-shrink-0 w-12">
                    {getGeometryFamilyLabel(t, layer.geometry_type)}
                  </span>
                  <span className="text-sm text-foreground truncate flex-1" title={layer.dataset_name}>
                    {layer.dataset_name}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggleVisibility(layer.sort_order)}
                    className="flex-shrink-0 text-muted-foreground hover:text-foreground"
                    title={isVisible ? t('viewer.legend.hideLayer') : t('viewer.legend.showLayer')}
                  >
                    {isVisible ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  </button>
                </div>

                {/* Data-driven legend entries */}
                {sc?.column && isVisible && (
                  <div className="mt-1.5 ml-6 space-y-0.5">
                    {sc.mode === 'categorical' && sc.categories && (
                      <>
                        {sc.categories.map((cat, i) => (
                          <div key={i} className="flex items-center gap-1.5">
                            <div
                              className="w-3 h-3 rounded-sm flex-shrink-0"
                              style={{ backgroundColor: cat.color }}
                            />
                            <span className="text-[11px] text-muted-foreground truncate">{cat.value}</span>
                          </div>
                        ))}
                      </>
                    )}
                    {sc.mode === 'graduated' && sc.breaks && sc.colors && (
                      <>
                        {sc.colors.map((clr, i) => {
                          const breaks = sc.breaks!;
                          let label: string;
                          if (i === 0) {
                            label = `< ${breaks[0]}`;
                          } else if (i === breaks.length) {
                            label = `>= ${breaks[breaks.length - 1]}`;
                          } else {
                            label = `${breaks[i - 1]} - ${breaks[i]}`;
                          }
                          return (
                            <div key={i} className="flex items-center gap-1.5">
                              <div
                                className="w-3 h-3 rounded-sm flex-shrink-0"
                                style={{ backgroundColor: clr }}
                              />
                              <span className="text-[11px] text-muted-foreground truncate">{label}</span>
                            </div>
                          );
                        })}
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
