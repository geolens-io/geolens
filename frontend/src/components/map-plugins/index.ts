// Side-effect: register all built-in plugins at import time
import './register-plugins';


export { getPlugins } from './registry';
export { PluginHost, PluginSidebar, usePartitionedPlugins } from './PluginHost';

export {
  getDefaultPluginIds,
  getEnabledPluginDefinitions,
  isPluginIdAvailable,
  resolveAvailablePluginIds,
  samePluginIds,
} from './plugin-availability';
