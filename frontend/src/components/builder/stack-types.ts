// Shared types for the unified stack sub-components, in a sibling file so the
// sortable wrappers don't import the 1200-line UnifiedStackPanel module.

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
  /** Raw basemap_config is non-null → "Reset appearance" has work to do. */
  hasCustomAppearance?: boolean;
}
