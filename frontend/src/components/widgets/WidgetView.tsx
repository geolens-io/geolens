import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { logger } from '@/lib/logger';
import { pushReportEntry } from '@/lib/report';
import type { ColumnLabel, WidgetRenderProps, WidgetSelection } from './contract';
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

/**
 * Renders one parsed instance: its lazy renderer, with the text fallback while
 * loading or on failure. `selection` and `onSelect` come from a host that
 * links widgets; see `WidgetRenderProps`. A host that serves uploaded images
 * passes the path of the one an image instance names (`assetPathFor` for the several a gallery names), and a text widget starts
 * its headings at `headingLevel`. `columnLabel` names the columns a widget
 * shows; see `WidgetRenderProps`.
 */
export function WidgetView({
  parsed,
  data,
  selection,
  onSelect,
  mapHidden,
  onLoadMore,
  loadingMore,
  onZoomTo,
  assetPath,
  assetPathFor,
  columnLabel,
  headingLevel,
  loadingFallback,
}: {
  parsed: ParsedWidget;
  data?: unknown;
  selection?: WidgetSelection | null;
  onSelect?: (selection: WidgetSelection | null) => void;
  mapHidden?: boolean;
  onLoadMore?: () => void;
  loadingMore?: boolean;
  onZoomTo?: WidgetRenderProps<unknown>['onZoomTo'];
  assetPath?: string;
  assetPathFor?: WidgetRenderProps<unknown>['assetPathFor'];
  columnLabel?: ColumnLabel;
  headingLevel?: WidgetRenderProps<unknown>['headingLevel'];
  /** Shown while the renderer loads, in place of the text fallback, which still covers a failed load. */
  loadingFallback?: ReactNode;
}) {
  if (!parsed.ok) return <UnavailableWidget />;
  const { definition, instance } = parsed;
  const fallback = (
    <definition.Fallback
      config={instance.config}
      data={data}
      selection={selection}
      assetPath={assetPath}
      assetPathFor={assetPathFor}
      columnLabel={columnLabel}
      headingLevel={headingLevel}
    />
  );
  return (
    <WidgetErrorBoundary type={definition.type} fallback={fallback}>
      <Suspense fallback={loadingFallback ?? fallback}>
        <definition.Renderer
          config={instance.config}
          data={data}
          selection={selection}
          onSelect={onSelect}
          mapHidden={mapHidden}
          onLoadMore={onLoadMore}
          loadingMore={loadingMore}
          onZoomTo={onZoomTo}
          assetPath={assetPath}
          assetPathFor={assetPathFor}
          columnLabel={columnLabel}
          headingLevel={headingLevel}
        />
      </Suspense>
    </WidgetErrorBoundary>
  );
}
