import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { logger } from '@/lib/logger';
import { pushReportEntry } from '@/lib/report';

interface PanelErrorBoundaryState {
  hasError: boolean;
  resetKey: number;
}

interface PanelErrorBoundaryProps {
  children: ReactNode;
  /** Log prefix identifying which panel crashed (e.g. "builder-sidebar"). */
  panelId: string;
}

function PanelErrorFallback({ onReset }: { onReset: () => void }) {
  const { t } = useTranslation('common');

  return (
    <div className="flex h-full w-full items-center justify-center p-4">
      <div className="text-center space-y-2 max-w-[16rem]">
        <AlertCircle className="mx-auto size-6 text-destructive" />
        <h3 className="text-sm font-semibold">{t('errorBoundary.panelTitle')}</h3>
        <p className="text-xs text-muted-foreground">
          {t('errorBoundary.panelMessage')}
        </p>
        <Button variant="outline" size="sm" onClick={onReset}>
          {t('errorBoundary.lazyRetry')}
        </Button>
      </div>
    </div>
  );
}

/**
 * fix(#394) UX-01/B-027: recoverable boundary for builder side panels. A render
 * error inside the sidebar previously crashed the whole builder page even
 * though the map and chat were healthy. The `resetKey` remounts the children
 * on retry, mirroring MapErrorBoundary.
 */
export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  constructor(props: PanelErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, resetKey: 0 };
  }

  static getDerivedStateFromError(): Partial<PanelErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error(`[PanelErrorBoundary:${this.props.panelId}]`, error, errorInfo);
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: error.message || `${this.props.panelId} crash`,
      detail: errorInfo.componentStack ?? error.stack ?? undefined,
    });
  }

  private handleReset = () => {
    this.setState((prev) => ({ hasError: false, resetKey: prev.resetKey + 1 }));
  };

  render() {
    if (this.state.hasError) {
      return <PanelErrorFallback onReset={this.handleReset} />;
    }
    return <div key={this.state.resetKey} className="contents">{this.props.children}</div>;
  }
}
