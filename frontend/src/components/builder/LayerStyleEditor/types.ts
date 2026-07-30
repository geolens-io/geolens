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
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  /** Patch a single paint property (handles builder-alias routing internally). */
  onPaintProp: (key: string, value: unknown) => void;
  /**
   * EDIT-05: Dedicated fill-pattern change handler. Enforces mutual exclusion:
   * setting a pattern deletes fill-color; clearing the pattern (id=undefined)
   * deletes fill-pattern and restores fill-color. Optional — only FillEditor uses it.
   */
  /** fix(#922): required — the fallback set fill-pattern to undefined instead of
   *  deleting the key, exactly what the EDIT-05 mutual-exclusion rule forbids. */
  onFillPatternChange: (id: string | undefined) => void;
  onToggleFill: () => void;
  onToggleStroke: () => void;
  onHeatmapPaintChange: (layerId: string, nextPaint: Record<string, unknown>) => void;
  onSymbolConfigChange: (patch: SymbolStyleConfig) => void;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}
