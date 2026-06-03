import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { logger } from '@/lib/logger';

interface MapErrorBoundaryState {
  hasError: boolean;
  resetKey: number;
}

interface MapErrorBoundaryProps {
  children: ReactNode;
  hasUnsavedChanges?: boolean;
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
  }

  private handleReset = () => {
    this.setState((prev) => ({ hasError: false, resetKey: prev.resetKey + 1 }));
  };

  render() {
    if (this.state.hasError) {
      return (
        <MapErrorFallback
          hasUnsavedChanges={this.props.hasUnsavedChanges}
          onReset={this.handleReset}
        />
      );
    }
    return <div key={this.state.resetKey} className="h-full">{this.props.children}</div>;
  }
}
