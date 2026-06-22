import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { logger } from '@/lib/logger';
import { pushReportEntry } from '@/lib/report';

interface MapErrorBoundaryState {
  hasError: boolean;
  resetKey: number;
}

interface MapErrorBoundaryProps {
  children: ReactNode;
  hasUnsavedChanges?: boolean;
  /**
   * Layout classes for the wrapper. Defaults to `h-full`, which relies on the
   * parent providing a definite height (the builder does, via an explicit
   * `h-[calc(...)]` ancestor). The public viewer's parent gets its height from
   * `flex-1`, which is not a definite height for a percentage-height child, so
   * the viewer passes `absolute inset-0` to size the map against its relative
   * `#map-viewport` container instead.
   */
  className?: string;
}

function MapErrorFallback({
  hasUnsavedChanges,
  onReset,
}: {
  hasUnsavedChanges?: boolean;
  onReset: () => void;
}) {
  const { t } = useTranslation('common');

  return (
    <div className="flex h-full w-full items-center justify-center bg-muted/30">
      <div className="text-center space-y-3 max-w-sm p-6">
        <AlertCircle className="mx-auto size-8 text-destructive" />
        <h3 className="text-sm font-semibold">{t('errorBoundary.mapTitle')}</h3>
        <p className="text-xs text-muted-foreground">
          {t('errorBoundary.mapMessage')}
        </p>
        {hasUnsavedChanges && (
          <p className="text-xs text-warning font-medium">
            {t('errorBoundary.builderUnsavedWarning')}
          </p>
        )}
        <Button variant="outline" size="sm" onClick={onReset}>
          {t('errorBoundary.mapRetry')}
        </Button>
      </div>
    </div>
  );
}

export class MapErrorBoundary extends Component<MapErrorBoundaryProps, MapErrorBoundaryState> {
  constructor(props: MapErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, resetKey: 0 };
  }

  static getDerivedStateFromError(): Partial<MapErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error('[MapErrorBoundary]', error, errorInfo);
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: error.message || 'Map crash',
      detail: errorInfo.componentStack ?? error.stack ?? undefined,
    });
  }

  private handleReset = () => {
    this.setState((prev) => ({ hasError: false, resetKey: prev.resetKey + 1 }));
  };

  render() {
    // Apply the same sizing wrapper to BOTH branches so the error/retry UI gets a
    // definite-height box too. In the public viewer this is `absolute inset-0`; the
    // fallback's own `h-full` would otherwise land back on the broken flex-derived
    // percentage-height path and render blank/clipped.
    const wrapperClassName = this.props.className ?? 'h-full';
    if (this.state.hasError) {
      return (
        <div className={wrapperClassName}>
          <MapErrorFallback
            hasUnsavedChanges={this.props.hasUnsavedChanges}
            onReset={this.handleReset}
          />
        </div>
      );
    }
    return (
      <div key={this.state.resetKey} className={wrapperClassName}>
        {this.props.children}
      </div>
    );
  }
}
