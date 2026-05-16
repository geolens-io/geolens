import type { BuilderStyleConfig, MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';

export type PointRenderMode = 'points' | 'heatmap' | 'symbol' | 'cluster';

/**
 * Shared props passed to every per-render-mode editor sub-component.
 * All editors receive the same interface so RenderModeSwitch can pass
 * them through uniformly.
 */
export interface BaseStyleEditorProps {
  layer: MapLayerResponse;
  /** Merged paint: layer.paint + builder overrides (builder-canonical view). */
  paint: Record<string, unknown>;
  /** True when a data-driven style config is active. */
  isDataDriven: boolean;
  builderConfig: BuilderStyleConfig;
  styleConfig: StyleConfig | null;
  symbolConfig: SymbolStyleConfig;
  /** Effective render mode (point layers only). */
  renderMode: PointRenderMode;
  /** True when layer is a polygon (vs pure POINT geometry). */
  isPolygon: boolean;
  /** Numeric columns available for height extrusion etc. */
  numericColumns: { name: string; type: string }[];
  /** Currently selected height column identifier (may be ''). */
  currentHeightCol: string;
  /** True when stroke is currently enabled. */
  strokeEnabled: boolean;
  /** True when fill is currently enabled (polygon only). */
  fillEnabled: boolean;
  /** True when the cluster render mode is available for this layer. */
  clusterAvailable: boolean;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: PointRenderMode) => void;
  /** Patch a single paint property (handles builder-alias routing internally). */
  onPaintProp: (key: string, value: unknown) => void;
  onToggleFill: () => void;
  onToggleStroke: () => void;
  onHeatmapPaintChange: (layerId: string, nextPaint: Record<string, unknown>) => void;
  onSymbolConfigChange: (patch: SymbolStyleConfig) => void;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}
