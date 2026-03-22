import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface LazyLoadErrorBoundaryState {
  hasError: boolean;
  retryCount: number;
  isRetrying: boolean;
}

interface LazyLoadErrorBoundaryProps {
  children: ReactNode;
}

function isChunkLoadError(error: Error): boolean {
  return (
    error.name === 'ChunkLoadError' ||
    error.message?.includes('Loading chunk') ||
    error.message?.includes('dynamically imported module')
  );
}

function LazyLoadFallback({
  isRetrying,
  onRetry,
}: {
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const { t } = useTranslation('common');

  if (isRetrying) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-center space-y-3">
          <Loader2 className="mx-auto size-6 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {t('errorBoundary.lazyRetrying')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center p-8">
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center max-w-sm">
        <AlertCircle className="mx-auto size-8 text-destructive mb-3" />
        <h3 className="text-sm font-semibold mb-1">
          {t('errorBoundary.lazyTitle')}
        </h3>
        <p className="text-xs text-muted-foreground mb-4">
          {t('errorBoundary.lazyMessage')}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t('errorBoundary.lazyRetry')}
        </Button>
      </div>
    </div>
  );
}

export class LazyLoadErrorBoundary extends Component<
  LazyLoadErrorBoundaryProps,
  LazyLoadErrorBoundaryState
> {
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(props: LazyLoadErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, retryCount: 0, isRetrying: false };
  }

  static getDerivedStateFromError(): Partial<LazyLoadErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[LazyLoadErrorBoundary]', error, errorInfo);

    // Auto-retry once for chunk load errors
    if (isChunkLoadError(error) && this.state.retryCount < 1) {
      this.setState({ isRetrying: true, retryCount: this.state.retryCount + 1 });
      this.retryTimer = setTimeout(() => {
        this.setState({ hasError: false, isRetrying: false });
      }, 1000);
    }
  }

  componentWillUnmount(): void {
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
    }
  }

  private handleRetry = () => {
    this.setState({ hasError: false, isRetrying: false });
  };

  render() {
    if (this.state.hasError || this.state.isRetrying) {
      return (
        <LazyLoadFallback
          isRetrying={this.state.isRetrying}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}
