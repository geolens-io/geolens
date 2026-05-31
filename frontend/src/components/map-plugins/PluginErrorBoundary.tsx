import { Component, type ReactNode } from 'react';
import type { TFunction } from 'i18next';

class PluginErrorBoundary extends Component<
  { t: TFunction; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error('Plugin error:', error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div role="alert" className="plugin-error">
          {this.props.t('widgets.widgetError')}
        </div>
      );
    }
    return this.props.children;
  }
}

export { PluginErrorBoundary };
