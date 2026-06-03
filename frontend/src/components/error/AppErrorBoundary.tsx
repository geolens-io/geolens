import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { logger } from '@/lib/logger';
import { ErrorReportButton } from './ErrorReportButton';

interface AppErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface AppErrorBoundaryProps {
  children: ReactNode;
}

function AppErrorFallback({ error }: { error: Error | null }) {
  const { t, ready } = useTranslation('common');

  const title = ready ? t('errorBoundary.appTitle') : 'Something went wrong';
  const message = ready ? t('errorBoundary.appMessage') : 'An unexpected error occurred. Please reload the page to continue.';
  const reload = ready ? t('errorBoundary.appReload') : 'Reload page';

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center max-w-md">
        <AlertCircle className="mx-auto size-8 text-destructive mb-3" />
        <h2 className="text-lg font-semibold mb-1">{title}</h2>
        <p className="text-sm text-destructive mb-1">{message}</p>
        {error && (
          <p className="text-xs text-muted-foreground mb-4 font-mono break-all">
            {error.message}
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => window.location.reload()}
          >
            {reload}
          </Button>
          <ErrorReportButton />
        </div>
      </div>
    </div>
  );
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  constructor(props: AppErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error('[AppErrorBoundary]', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <AppErrorFallback error={this.state.error} />;
    }
    return this.props.children;
  }
}
