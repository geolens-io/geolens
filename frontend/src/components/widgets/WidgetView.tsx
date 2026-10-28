import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { logger } from '@/lib/logger';
import { pushReportEntry } from '@/lib/report';
import type { ParsedWidget } from './registry';

/** Shows the widget's fallback when its renderer fails to load or crashes. */
class WidgetErrorBoundary extends Component<
  { type: string; fallback: ReactNode; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error(`Widget "${this.props.type}" failed:`, error, info.componentStack);
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: error.message || `Widget "${this.props.type}" failed`,
      detail: info.componentStack ?? error.stack ?? undefined,
    });
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

function UnavailableWidget() {
  const { t } = useTranslation('widgets');
  return (
    <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
      {t('unavailable')}
    </p>
  );
}

/** Renders one parsed instance: its lazy renderer, with the text fallback while loading or on failure. */
export function WidgetView({ parsed, data }: { parsed: ParsedWidget; data?: unknown }) {
  if (!parsed.ok) return <UnavailableWidget />;
  const { definition, instance } = parsed;
  const fallback = <definition.Fallback config={instance.config} data={data} />;
  return (
    <WidgetErrorBoundary type={definition.type} fallback={fallback}>
      <Suspense fallback={fallback}>
        <definition.Renderer config={instance.config} data={data} />
      </Suspense>
    </WidgetErrorBoundary>
  );
}
