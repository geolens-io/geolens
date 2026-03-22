import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface AppErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface AppErrorBoundaryProps {
  children: ReactNode;
}

function AppErrorFallback({ error }: { error: Error | null }) {
  let title = 'Something went wrong';
  let message = 'An unexpected error occurred. Please reload the page to continue.';
  let reload = 'Reload page';

  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { t } = useTranslation('common');
    title = t('errorBoundary.appTitle');
    message = t('errorBoundary.appMessage');
    reload = t('errorBoundary.appReload');
  } catch {
    // i18n not available — use hardcoded English fallbacks above
  }

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
        <Button
          variant="destructive"
          size="sm"
          onClick={() => window.location.reload()}
        >
          {reload}
        </Button>
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
    console.error('[AppErrorBoundary]', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <AppErrorFallback error={this.state.error} />;
    }
    return this.props.children;
  }
}
