// builder-audit #338 STACK-05: shared types for the unified stack sub-components,
// extracted from UnifiedStackPanel.tsx so the sortable wrappers can live in
// sibling files without importing the 1200-line panel module.

export interface BasemapSublayerInfo {
  id: string;
  name: string;
  visible: boolean;
  opacity: number;
  kind: 'vector' | 'raster';
}

export interface BasemapGroupInfo {
  id: string;
  presetName: string;
  providerLabel?: string;
  visible: boolean;
  opacity: number;
  sublayers: BasemapSublayerInfo[];
  /** fix(#585): raw basemap_config is non-null → "Reset appearance" has work to do. */
  hasCustomAppearance?: boolean;
}
