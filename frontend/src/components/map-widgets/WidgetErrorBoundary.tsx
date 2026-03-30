import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n/i18n';

/** Isolates widget crashes so one broken widget doesn't take down the host */
export class WidgetErrorBoundary extends Component<
  { widgetId: string; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Widget "${this.props.widgetId}" crashed:`, error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-2.5 text-xs text-destructive">
          {i18n.t('builder:widgets.widgetError')}
        </div>
      );
    }
    return this.props.children;
  }
}
