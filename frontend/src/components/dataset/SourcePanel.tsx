import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { AlertCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  useCancelRefreshJob,
  useDatasetRefreshRuns,
  useDatasetVersions,
} from '@/components/dataset/hooks/use-dataset';
import { OriginBadge, datasetOrigin } from '@/components/dataset/OriginBadge';
import { useVrtGenerations, useVrtSources, useVrtStatus } from '@/components/import/hooks/use-vrt';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatDateTimeSmart, formatNumber } from '@/lib/format';
import {
  healthDotColors,
  refreshRunStatusColors,
  semanticBadgeColors,
  vrtGenerationColors,
} from '@/lib/status-colors';
import { useAuthStore } from '@/stores/auth-store';
import type {
  DatasetOrigin,
  DatasetResponse,
  DatasetVersionResponse,
  SchemaDriftStatus,
  SourceFreshness,
  SourceHealth,
  VrtSourceHealth,
} from '@/types/api';

export interface SourcePanelProps {
  dataset: DatasetResponse;
  /** Injected by the caller (DetailPanel wires the #1285 "Refresh from
   *  source" action here, gated on canEdit and a resolvable origin). The
   *  read-only #1225 integration passed nothing. */
  actions?: ReactNode;
  /** feat(#1677): the same owner-or-admin signal that gates the injected
   *  refresh action, minus the origin gate — cancel rights are a superset
   *  of refresh rights on this surface (a run can be in flight on a dataset
   *  whose origin no longer resolves). Gates the Cancel button on the
   *  active run row in the refresh history. */
  canEdit?: boolean;
}

type PointerField = {
  label: 'filename' | 'fingerprint' | 'table' | 'serviceType' | 'layer' | 'endpoint' | 'collection' | 'asset' | 'item';
  value: string;
};

type HealthDetail =
  | 'not_found'
  | 'item_withdrawn'
  | 'unauthorized'
  | 'server_error'
  | 'unexpected_status'
  | 'timeout'
  | 'network_error'
  | 'blocked_by_policy';

const HEALTH_DETAILS = new Set<HealthDetail>([
  'not_found',
  'item_withdrawn',
  'unauthorized',
  'server_error',
  'unexpected_status',
  'timeout',
  'network_error',
  'blocked_by_policy',
]);

const healthClasses: Record<SourceHealth, string> = {
  healthy: semanticBadgeColors.success,
  missing: semanticBadgeColors.destructive,
  inaccessible: semanticBadgeColors.warning,
  unknown: 'border-border bg-muted text-muted-foreground',
};

const freshnessClasses: Record<SourceFreshness, string> = {
  fresh: semanticBadgeColors.success,
  due: semanticBadgeColors.warning,
  overdue: semanticBadgeColors.destructive,
  unknown: 'border-border bg-muted text-muted-foreground',
};

const driftClasses: Record<SchemaDriftStatus, string> = {
  none: semanticBadgeColors.success,
  drifted: semanticBadgeColors.destructive,
  unknown: 'border-border bg-muted text-muted-foreground',
};

function refString(ref: Record<string, unknown> | null | undefined, key: string): string | null {
  const value = ref?.[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

/**
 * Render provenance URLs without transporting credentials into the DOM.
 * The backend already rejects credential-bearing origin pointers; this is a
 * defensive display boundary for old rows and malformed test/overlay payloads.
 */
function safeHttpPointer(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch {
    return null;
  }
}

function trustedRef(dataset: DatasetResponse, origin: DatasetOrigin): Record<string, unknown> | null {
  const ref = dataset.origin_ref;
  return ref && ref.kind === origin ? ref : null;
}

function pointerFields(dataset: DatasetResponse, origin: DatasetOrigin | null): PointerField[] {
  if (!origin) return [];
  const ref = trustedRef(dataset, origin);

  if (origin === 'upload') {
    const filename = refString(ref, 'filename') ?? dataset.source_filename;
    const fingerprint = refString(ref, 'file_hash');
    return [
      ...(filename ? [{ label: 'filename' as const, value: filename }] : []),
      ...(fingerprint ? [{ label: 'fingerprint' as const, value: fingerprint }] : []),
    ];
  }

  if (origin === 'postgis') {
    const table = refString(ref, 'table_name');
    return table ? [{ label: 'table', value: table }] : [];
  }

  if (origin === 'service') {
    const serviceType = refString(ref, 'service_type');
    const layer = refString(ref, 'layer_id');
    const endpoint = safeHttpPointer(refString(ref, 'url') ?? dataset.origin_uri ?? null);
    return [
      ...(serviceType ? [{ label: 'serviceType' as const, value: serviceType }] : []),
      ...(layer ? [{ label: 'layer' as const, value: layer }] : []),
      ...(endpoint ? [{ label: 'endpoint' as const, value: endpoint }] : []),
    ];
  }

  if (origin === 'stac') {
    const collection = refString(ref, 'collection_id');
    const asset = refString(ref, 'asset_key');
    const item = safeHttpPointer(refString(ref, 'item_href'));
    const assetHref = safeHttpPointer(
      refString(ref, 'asset_href') ?? dataset.origin_uri ?? null,
    );
    return [
      ...(collection ? [{ label: 'collection' as const, value: collection }] : []),
      ...(asset ? [{ label: 'asset' as const, value: asset }] : []),
      ...(item ? [{ label: 'item' as const, value: item }] : []),
      ...(assetHref ? [{ label: 'endpoint' as const, value: assetHref }] : []),
    ];
  }

  return [];
}

function StatusBadge({
  kind,
  value,
}: {
  kind: 'health' | 'freshness' | 'drift';
  value: SourceHealth | SourceFreshness | SchemaDriftStatus;
}) {
  const { t } = useTranslation('dataset');
  const classes = kind === 'health'
    ? healthClasses[value as SourceHealth]
    : kind === 'freshness'
      ? freshnessClasses[value as SourceFreshness]
      : driftClasses[value as SchemaDriftStatus];

  return (
    <Badge variant="outline" className={classes}>
      {t(`sourcePanel.status.${kind}.${value}`)}
    </Badge>
  );
}

function SourceMetric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1 rounded-md border border-border/70 bg-surface-2/30 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

function SourceHistory({ dataset }: { dataset: DatasetResponse }) {
  const { t, i18n } = useTranslation('dataset');
  const { data, isLoading, isError } = useDatasetVersions(dataset.id);
  const fetched = (data?.versions ?? []).filter((version) => version.dataset_id === dataset.id);
  const hasFirstVersion = fetched.some((version) => version.version_number === 1);
  // fix(#1280): current fields cannot reconstruct mutable version-1 state.
  const currentFieldsAreInitial = dataset.current_version === 1;
  const versions: DatasetVersionResponse[] = [
    ...fetched,
    ...(!hasFirstVersion
      ? [{
          id: 'source-panel-v1',
          dataset_id: dataset.id,
          version_number: 1,
          source_filename: currentFieldsAreInitial ? dataset.source_filename : null,
          source_format: currentFieldsAreInitial ? dataset.source_format : null,
          feature_count: null,
          srid: currentFieldsAreInitial ? dataset.srid : null,
          geometry_type: currentFieldsAreInitial ? dataset.geometry_type : null,
          file_hash: null,
          uploaded_by: dataset.created_by,
          uploaded_at: dataset.created_at,
        }]
      : []),
  ]
    .sort((a, b) => b.version_number - a.version_number)
    .slice(0, 5);

  return (
    <section aria-labelledby="source-history-heading" className="space-y-3">
      <h2 id="source-history-heading" className="text-base font-semibold">
        {t('sourcePanel.history.title')}
      </h2>
      {isLoading ? (
        <div className="space-y-2" aria-label={t('sourcePanel.history.loading')}>
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">{t('sourcePanel.history.loadFailed')}</p>
      ) : (
        <ol className="space-y-3">
          {versions.map((version) => (
            <li key={version.id} className="border-s-2 border-muted ps-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">
                  {t('sourcePanel.history.version', { number: version.version_number })}
                </span>
                {version.version_number === dataset.current_version && (
                  <Badge variant="secondary">{t('sourcePanel.history.current')}</Badge>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatDateTimeSmart(version.uploaded_at)}
                {' · '}
                {version.source_filename ?? t('sourcePanel.history.catalogUpdate')}
                {version.feature_count != null
                  ? ` · ${t('sourcePanel.history.features', {
                      count: version.feature_count,
                      formattedCount: version.feature_count.toLocaleString(i18n.language),
                    })}`
                  : ''}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Read-only history of refresh attempts (#1285), including failures — the
 * durable record `SourceRefreshAction` dispatches into via `POST .../refresh`
 * and that its dataset_busy gating reads back from. Visible to anyone who can
 * see the dataset at all; the backend redacts triggered_by/error detail for
 * non-owner, non-admin readers rather than hiding the section outright.
 */
function RefreshRunHistory({ dataset, canEdit }: { dataset: DatasetResponse; canEdit: boolean }) {
  const { t, i18n } = useTranslation('dataset');
  const { data, isLoading, isError } = useDatasetRefreshRuns(dataset.id, { limit: 5 });
  const cancelRefreshJob = useCancelRefreshJob();
  const runs = data?.runs ?? [];

  return (
    <section aria-labelledby="refresh-history-heading" className="space-y-3">
      <h2 id="refresh-history-heading" className="text-base font-semibold">
        {t('sourcePanel.refresh.history.title')}
      </h2>
      {isLoading ? (
        <div className="space-y-2" aria-label={t('sourcePanel.refresh.history.loading')}>
          <Skeleton className="h-14 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">{t('sourcePanel.refresh.history.loadFailed')}</p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('sourcePanel.refresh.history.empty')}</p>
      ) : (
        <ol className="space-y-3">
          {runs.map((run) => (
            <li key={run.id} className="border-s-2 border-muted ps-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={refreshRunStatusColors[run.status] ?? ''}>
                  {t(`sourcePanel.refresh.history.status.${run.status}`, { defaultValue: run.status })}
                </Badge>
                {/* fix(#1325): run.origin_kind is the run's execution door,
                    not the dataset's origin shown by the OriginBadge above —
                    the two can visibly disagree while work is in flight (see
                    the CHECK constraint comment in refresh/models.py for a
                    concrete case). The label reads "Method: <value>" and the
                    tooltip spells out that it is not the dataset's origin,
                    so this row never reads as a second, competing origin
                    claim. */}
                <Badge
                  variant="secondary"
                  title={t('sourcePanel.refresh.history.mechanismTooltip')}
                >
                  {t('sourcePanel.refresh.history.mechanismLabel', { mechanism: run.origin_kind })}
                </Badge>
                {/* feat(#1677): one-click cancel on the active run, Retry
                    parity — no confirm dialog; recoverable and data-safe
                    under the backend's no-swap fence. Keyed on the run's
                    ingest_job_id (absent on legacy rows, so gated on it). */}
                {canEdit
                  && (run.status === 'pending' || run.status === 'running')
                  && run.ingest_job_id && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="ms-auto"
                    onClick={() =>
                      cancelRefreshJob.mutate(
                        { jobId: run.ingest_job_id as string, datasetId: dataset.id },
                        {
                          onError: () => {
                            toast.error(t('sourcePanel.refresh.cancelFailed'));
                          },
                        },
                      )
                    }
                    disabled={cancelRefreshJob.isPending}
                  >
                    {cancelRefreshJob.isPending
                      ? t('sourcePanel.refresh.cancelling')
                      : t('sourcePanel.refresh.cancel')}
                  </Button>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatDateTimeSmart(run.started_at)}
                {run.feature_count_before != null && run.feature_count_after != null
                  ? ` · ${t('sourcePanel.refresh.history.featureDelta', {
                      before: run.feature_count_before.toLocaleString(i18n.language),
                      after: run.feature_count_after.toLocaleString(i18n.language),
                    })}`
                  : ''}
                {run.triggered_by_username
                  ? ` · ${t('sourcePanel.refresh.history.triggeredBy', { username: run.triggered_by_username })}`
                  : ''}
              </p>
              {run.status === 'failed' && run.error_message && (
                <p className="mt-1 text-xs text-destructive">{run.error_message}</p>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function VrtMemberHealth({ status }: { status: VrtSourceHealth['status'] | undefined }) {
  const { t } = useTranslation('dataset');
  const resolved = status ?? 'unknown';
  const dotClass = resolved === 'healthy'
    ? healthDotColors.healthy
    : resolved === 'unknown'
      ? healthDotColors.unknown
      : healthDotColors.unhealthy;

  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden="true" className={`inline-block size-2 rounded-full ${dotClass}`} />
      {t(`sourcePanel.vrt.memberHealth.${resolved}`)}
    </span>
  );
}

function VrtSection({ dataset, isAuthenticated }: { dataset: DatasetResponse; isAuthenticated: boolean }) {
  const { t, i18n } = useTranslation('dataset');
  const isRegenerating = dataset.raster?.status === 'regenerating';
  const queryId = isAuthenticated ? dataset.id : '';
  const { data: sourcesData, isLoading, isError } = useVrtSources(queryId);
  const { data: statusData } = useVrtStatus(queryId, isRegenerating);
  const { data: generationsData } = useVrtGenerations(queryId);
  const sources = sourcesData?.sources ?? [];
  const healthById = new Map<string, VrtSourceHealth['status']>();
  statusData?.source_health.forEach((health) => healthById.set(health.dataset_id, health.status));

  return (
    <section aria-labelledby="vrt-members-heading" className="space-y-4">
      <div>
        <h2 id="vrt-members-heading" className="text-base font-semibold">
          {t('sourcePanel.vrt.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('sourcePanel.vrt.description')}
        </p>
      </div>

      {isRegenerating && (
        <div className="flex items-center gap-2 rounded-md border border-info/30 bg-info/5 px-4 py-3 text-sm">
          <Loader2 aria-hidden="true" className="size-4 animate-spin text-info" />
          {t('sourcePanel.vrt.regenerating')}
        </div>
      )}
      {dataset.raster?.status === 'failed' && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <AlertCircle aria-hidden="true" className="size-4" />
          {t('sourcePanel.vrt.failed')}
        </div>
      )}

      {!isAuthenticated ? (
        <p className="rounded-md border border-border/70 bg-muted/30 p-4 text-sm text-muted-foreground">
          {t('sourcePanel.vrt.signIn')}
        </p>
      ) : isLoading ? (
        <div className="space-y-2" aria-label={t('sourcePanel.vrt.loading')}>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-destructive">{t('sourcePanel.vrt.loadFailed')}</p>
      ) : (
        <Table aria-label={t('sourcePanel.vrt.tableLabel')}>
          <TableHeader>
            <TableRow>
              <TableHead>{t('sourcePanel.vrt.health')}</TableHead>
              <TableHead>{t('sourcePanel.vrt.position')}</TableHead>
              <TableHead>{t('sourcePanel.vrt.dataset')}</TableHead>
              <TableHead>{t('sourcePanel.vrt.crs')}</TableHead>
              <TableHead>{t('sourcePanel.vrt.bands')}</TableHead>
              <TableHead>{t('sourcePanel.vrt.resolution')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sources.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                  {t('sourcePanel.vrt.empty')}
                </TableCell>
              </TableRow>
            ) : sources.map((source) => (
              <TableRow key={source.dataset_id}>
                <TableCell><VrtMemberHealth status={healthById.get(source.dataset_id)} /></TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {source.position + 1}
                </TableCell>
                <TableCell>
                  <Link to={`/datasets/${source.dataset_id}`} className="text-primary hover:underline">
                    {source.title}
                  </Link>
                </TableCell>
                <TableCell>{source.crs_epsg != null ? `EPSG:${source.crs_epsg}` : '—'}</TableCell>
                <TableCell>{source.band_count ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">
                  {source.resolution_x != null && source.resolution_y != null
                    ? `${formatNumber(source.resolution_x, { maximumFractionDigits: 4 })} × ${formatNumber(source.resolution_y, { maximumFractionDigits: 4 })}`
                    : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {isAuthenticated && generationsData && generationsData.generations.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">{t('sourcePanel.vrt.history')}</h3>
          <Table aria-label={t('sourcePanel.vrt.history')}>
            <TableHeader>
              <TableRow>
                <TableHead>{t('sourcePanel.vrt.generationStatus')}</TableHead>
                <TableHead>{t('sourcePanel.vrt.generatedAt')}</TableHead>
                <TableHead>{t('sourcePanel.vrt.duration')}</TableHead>
                <TableHead>{t('sourcePanel.vrt.sourceCount')}</TableHead>
                <TableHead>{t('sourcePanel.vrt.triggeredBy')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {generationsData.generations.map((generation) => (
                <TableRow key={generation.id}>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={vrtGenerationColors[generation.status] ?? ''}
                    >
                      {t(`sourcePanel.vrt.generation.${generation.status}`, {
                        defaultValue: generation.status,
                      })}
                    </Badge>
                  </TableCell>
                  <TableCell>{formatDateTimeSmart(generation.started_at)}</TableCell>
                  <TableCell>
                    {generation.duration_seconds != null
                      ? `${generation.duration_seconds.toLocaleString(i18n.language, { maximumFractionDigits: 1 })}s`
                      : '—'}
                  </TableCell>
                  <TableCell>{generation.source_count ?? '—'}</TableCell>
                  <TableCell>
                    {generation.triggered_by === 'system'
                      ? t('sourcePanel.vrt.system')
                      : generation.triggered_by
                        ? t('sourcePanel.vrt.user')
                        : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

export function SourcePanel({ dataset, actions, canEdit = false }: SourcePanelProps) {
  const { t } = useTranslation('dataset');
  const isAuthenticated = useAuthStore((state) => Boolean(state.token));
  const isVrt = dataset.record_type === 'vrt_dataset';
  const origin = dataset.origin ?? datasetOrigin(dataset);
  const pointers = pointerFields(dataset, origin);
  const health = dataset.source_health ?? 'unknown';
  const freshness = dataset.source_freshness ?? 'unknown';
  const drift = dataset.schema_drift_status ?? 'unknown';
  const healthDetail = dataset.source_health_detail;
  const translatedHealthDetail = healthDetail && HEALTH_DETAILS.has(healthDetail as HealthDetail)
    ? t(`sourcePanel.healthDetail.${healthDetail}`)
    : null;
  const originKey = isVrt ? 'vrt' : origin ?? 'unknown';
  const storageKey = isVrt ? 'vrt' : origin ?? 'unknown';

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle level={2}>{t('sourcePanel.title')}</CardTitle>
          {actions && <CardAction>{actions}</CardAction>}
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-2">
              {origin ? (
                <OriginBadge origin={origin} />
              ) : (
                <Badge variant="outline">{t(`sourcePanel.origin.${originKey}`)}</Badge>
              )}
              <p className="max-w-2xl text-sm text-muted-foreground">
                {t(`sourcePanel.description.${originKey}`)}
              </p>
            </div>
            <div className="text-end">
              <p className="text-xs text-muted-foreground">{t('sourcePanel.storageMode')}</p>
              <p className="text-sm font-medium">{t(`sourcePanel.storage.${storageKey}`)}</p>
            </div>
          </div>

          {pointers.length > 0 && (
            <dl className="grid gap-3 rounded-md border border-border/70 bg-muted/20 p-4 sm:grid-cols-2">
              {pointers.map((pointer) => (
                <div key={`${pointer.label}-${pointer.value}`} className="min-w-0">
                  <dt className="text-xs text-muted-foreground">
                    {t(`sourcePanel.pointer.${pointer.label}`)}
                  </dt>
                  <dd className="mt-1 break-all font-mono text-xs" title={pointer.value}>
                    {pointer.value}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <SourceMetric label={t('sourcePanel.lastRefreshed')}>
              {formatDateTimeSmart(dataset.last_refreshed_at ?? null)}
            </SourceMetric>
            <SourceMetric label={t('sourcePanel.lastChecked')}>
              {formatDateTimeSmart(dataset.last_checked_at ?? null)}
            </SourceMetric>
            <SourceMetric label={t('sourcePanel.featureCount')}>
              {formatNumber(dataset.feature_count)}
            </SourceMetric>
            <SourceMetric label={t('sourcePanel.health')}>
              <StatusBadge kind="health" value={health} />
              {translatedHealthDetail && (
                <span className="mt-1 block text-xs font-normal text-muted-foreground">
                  {translatedHealthDetail}
                </span>
              )}
            </SourceMetric>
            <SourceMetric label={t('sourcePanel.freshness')}>
              <StatusBadge kind="freshness" value={freshness} />
            </SourceMetric>
            <SourceMetric label={t('sourcePanel.drift')}>
              <StatusBadge kind="drift" value={drift} />
            </SourceMetric>
          </dl>
        </CardContent>
      </Card>

      {isVrt ? (
        <VrtSection dataset={dataset} isAuthenticated={isAuthenticated} />
      ) : (
        <>
          <SourceHistory dataset={dataset} />
          {/* Gated the same way SourceRefreshAction is: no origin, nothing
              could ever have been refreshed, so no history to show. */}
          {origin && <RefreshRunHistory dataset={dataset} canEdit={canEdit} />}
        </>
      )}
    </div>
  );
}
