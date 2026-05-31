import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n/i18n';
import { logger } from '@/lib/logger';

/** Isolates plugin crashes so one broken plugin doesn't take down the host */
export class PluginErrorBoundary extends Component<
  { pluginId: string; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error(`Plugin "${this.props.pluginId}" crashed:`, error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-2.5 text-xs text-destructive">
          {i18n.t('builder:plugins.pluginError')}
        </div>
      );
    }
    return this.props.children;
  }
}
