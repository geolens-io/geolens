// Side-effect: register all built-in widgets at import time
import './register-widgets';

export type { WidgetAnchor, WidgetPlacement, WidgetContext, WidgetDefinition } from './types';
export { registerWidget, getWidgets, getWidget } from './registry';
export { WidgetHost } from './WidgetHost';
export { WidgetPanel } from './WidgetPanel';
export { WidgetToolbar } from './WidgetToolbar';
export { WidgetSidebar } from './WidgetSidebar';
