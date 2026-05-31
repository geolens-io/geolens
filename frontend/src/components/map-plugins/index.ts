// Side-effect: register all built-in plugins at import time
import './register-plugins';

export type { PluginAnchor, PluginPlacement, PluginContext, PluginDefinition } from './types';
export { registerPlugin, getPlugins, getPlugin } from './registry';
export { PluginHost, PluginSidebar, usePartitionedPlugins } from './PluginHost';
export { PluginPanel } from './PluginPanel';
export {
  getDefaultPluginIds,
  getEnabledPluginDefinitions,
  isPluginIdAvailable,
  resolveAvailablePluginIds,
  samePluginIds,
} from './plugin-availability';
