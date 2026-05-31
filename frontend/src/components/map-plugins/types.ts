/**
 * Plugin platform types.
 *
 * A plugin is a self-contained UI surface rendered over the map (e.g. measurement,
 * legend). Plugins declare an anchor + placement and receive a typed context.
 */
export type PluginAnchor = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

export type PluginPlacement = 'inline' | 'panel';

export interface PluginContext {
  /** Stable map id the plugin is bound to. */
  mapId: string;
  /** i18n example key: 'widgets.measurement.label' */
  mapId2?: never;
}

export interface PluginDefinition {
  id: string;
  anchor: PluginAnchor;
  placement: PluginPlacement;
  component: React.ComponentType<{ context: PluginContext }>;
}
