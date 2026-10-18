import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  useDistributions,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { CopyButton } from '@/components/ui/copy-button';
import { cn } from '@/lib/utils';
import { exportFilename, isExportFormat } from '@/lib/export-formats';
import { URL_CHIP_CLASS } from '@/components/dataset/url-chip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Circle, CircleDot, Loader2, Download } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import {
  getPublicApiBaseUrl,
  resolveDistributionUrl,
  isAbsoluteUrl,
  isSameOriginAbsoluteUrl,
  isFetchableDistributionUrl,
  vectorTileUrlForClients,
} from '@/lib/dataset-access';
import { authenticatedDownload } from '@/api/datasets';
import type { DatasetVisibility, DistributionResponse } from '@/types/api';

interface DistributionsListProps {
  recordId: string;
  /** Owner-or-admin editor: mirrors the backend `require_permission("edit_metadata")`
   * + `_check_record_ownership` guard on the distribution PATCH endpoint.
   * Everyone else keeps the read-only view (#1395). */
  canEdit?: boolean;
  /** Names exported downloads after the dataset, e.g. `<title>.zip` for a shapefile. */
  datasetTitle?: string;
  /** A non-public dataset's own vector tile URL is listed with an API key placeholder. */
  visibility?: DatasetVisibility;
}

const TYPE_ORDER = ['download', 'api', 'tiles', 'other'] as const;
type DistributionGroup = (typeof TYPE_ORDER)[number];

const TYPE_LABEL_KEYS: Record<DistributionGroup, string> = {
  download: 'distributions.download',
  api: 'distributions.api',
  tiles: 'distributions.tiles',
  other: 'distributions.other',
};

const DISTRIBUTION_GROUPS: Record<string, DistributionGroup> = {
  download: 'download',
  api: 'api',
  ogcService: 'api',
  ogc_features: 'api',
  vector_tiles: 'tiles',
  tiles: 'tiles',
  webApp: 'other',
  offlineAccess: 'other',
  other: 'other',
};

/** Saved name for a row's download: the dataset title for a generated export, the row's own name otherwise. */
function distributionFilename(distribution: DistributionResponse, datasetTitle?: string): string {
  if (
    datasetTitle &&
    distribution.auto_generated &&
    distribution.distribution_type === 'download' &&
    isExportFormat(distribution.format)
  ) {
    return exportFilename(datasetTitle, distribution.format);
  }
  const base = (distribution.title?.trim() || distribution.distribution_type).replace(/[/\\]/g, '_');
  return `${base}.${distribution.format}`;
}

function CopyableUrl({
  distribution,
  publicApiUrl,
  datasetTitle,
  className,
}: {
  distribution: DistributionResponse;
  datasetTitle?: string;
  publicApiUrl: string | null | undefined;
  className?: string;
}) {
  const { t } = useTranslation('dataset');
  const [downloading, setDownloading] = useState(false);
  const resolvedUrl = resolveDistributionUrl(distribution.url, publicApiUrl);
  // Same-origin (relative, or absolute matching this
  // instance's own API) gets the bearer token; a genuinely external url
  // (e.g. a manual viewer-app link) must never receive it.
  const isSameOriginApiResource =
    !isAbsoluteUrl(distribution.url) || isSameOriginAbsoluteUrl(distribution.url);
  // A vector-tile row's url is a template
  // (/tiles/data.<table>/{z}/{x}/{y}.pbf — no literal resource at that
  // path) and a raster/VRT row's url is a bare object-storage key
  // (rasters/<id>/<sha>/source.cog.tif — not the real, token-gated COG
  // download route). Neither is something a single fetch resolves, so ONLY
  // an actually-fetchable url gets a download action at all; the rest stay
  // copy-only rows.
  const isFetchable = isFetchableDistributionUrl(distribution.url);

  // A plain <a href download> browser navigation carries no
  // Authorization header, so a private or unpublished dataset's export
  // endpoint rejected it as anonymous. Route same-origin GeoLens resources
  // through a refresh-aware, bearer-authenticated fetch-and-save flow
  // (api/datasets.ts's authenticatedDownload).
  async function handleAuthenticatedDownload() {
    if (downloading) return;
    setDownloading(true);
    try {
      await authenticatedDownload(resolvedUrl, distributionFilename(distribution, datasetTitle));
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t('distributions.downloadFailed', { defaultValue: 'Failed to download.' }),
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className={cn('flex min-w-0 items-center gap-2', className)}>
      <code className={URL_CHIP_CLASS} title={resolvedUrl}>
        {resolvedUrl}
      </code>
      {/* Copy alone cannot fetch the resource. Same-origin GeoLens
          resources download through the authenticated fetch flow (needed for
          private/unpublished datasets); an external URL from a manual
          distribution is a plain link instead — it is not ours to attach a
          bearer token to. A tile-template or bare-storage-key row (see
          isFetchable above) gets no download action at all — copy remains
          the only way to get the value, since there is nothing a single
          fetch or plain navigation could resolve. */}
      {isFetchable &&
        (isSameOriginApiResource ? (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={handleAuthenticatedDownload}
            disabled={downloading}
            aria-label={t('distributions.downloadUrl')}
            title={t('distributions.downloadUrl')}
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
          </Button>
        ) : (
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" asChild>
            <a
              href={resolvedUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t('distributions.downloadUrl')}
              title={t('distributions.downloadUrl')}
            >
              <Download className="h-3.5 w-3.5" />
            </a>
          </Button>
        ))}
      <CopyButton value={resolvedUrl} label={t('distributions.copyUrl')} />
    </div>
  );
}

/** Title alone can collide — `uq_record_distribution`
 * covers (record_id, distribution_type, format, url), not title, so two
 * manual rows are free to share one, and a truncated URL is only unique
 * up to whatever the truncation cuts off. The row's own
 * `id` is the one field the database actually guarantees is unique — use it
 * untruncated instead of a heuristic. */
function distributionLabel(distribution: DistributionResponse): string {
  const base =
    distribution.title?.trim() || distribution.format || distribution.distribution_type;
  return `${base} (${distribution.id})`;
}

/** Radio-style set-primary control. Rendered only for manual
 * (non-auto_generated) rows — `update_distribution` rejects any write,
 * `is_primary` included, against an auto_generated row with a 400, so a
 * control on those rows could never do anything but fail. The currently
 * primary manual row renders checked and disabled; clicking any other one
 * PATCHes it to `is_primary: true`, which the backend applies as a
 * last-write-wins demote of every other row on the record.
 *
 * `isMutating` disables every sibling control
 * while any promotion is in flight, not just the clicked one — two manual
 * rows both idle-looking would otherwise let a second click fire a
 * concurrent PATCH, and since both transactions demote-then-promote against
 * `uq_record_distribution_primary`, which one wins is transaction order, not
 * click order. `isPendingThisRow` only decides which button shows the
 * spinner. The accessible name (`distributionLabel`) identifies the row so a
 * screen reader can tell two "Set as primary" buttons apart. */
function SetPrimaryControl({
  distribution,
  onSelect,
  isMutating,
  isPendingThisRow,
}: {
  distribution: DistributionResponse;
  onSelect: (distributionId: string) => void;
  isMutating: boolean;
  isPendingThisRow: boolean;
}) {
  const { t } = useTranslation('dataset');
  const name = distributionLabel(distribution);
  const label = distribution.is_primary
    ? t('distributions.currentPrimary', { name })
    : t('distributions.setPrimary', { name });

  return (
    <Button
      variant="ghost"
      size="icon-xs"
      onClick={() => onSelect(distribution.id)}
      disabled={distribution.is_primary || isMutating}
      aria-label={label}
      title={label}
    >
      {isPendingThisRow ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : distribution.is_primary ? (
        <CircleDot className="h-3 w-3" />
      ) : (
        <Circle className="h-3 w-3" />
      )}
    </Button>
  );
}

export function getDistributionGroup(distributionType: string): DistributionGroup {
  return DISTRIBUTION_GROUPS[distributionType] ?? 'other';
}

function groupByType(
  distributions: DistributionResponse[],
): Map<DistributionGroup, DistributionResponse[]> {
  const groups = new Map<DistributionGroup, DistributionResponse[]>();
  for (const dist of distributions) {
    const type = getDistributionGroup(dist.distribution_type);
    const existing = groups.get(type) ?? [];
    existing.push(dist);
    groups.set(type, existing);
  }
  return groups;
}

export function DistributionsList({ recordId, canEdit = false, visibility = 'public', datasetTitle }: DistributionsListProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, error } = useDistributions(recordId);
  const { data: tileConfig } = useTileConfig();
  const publicApiBaseUrl = getPublicApiBaseUrl(tileConfig);
  const setPrimary = useSetPrimaryDistribution(recordId);

  if (isLoading) {
    return <LoadingState className="py-6" />;
  }

  if (error) {
    return (
      <p className="text-sm text-destructive py-4 text-center">
        {t('distributions.loadError', { defaultValue: 'Failed to load distributions.' })}
      </p>
    );
  }

  const distributions = (data?.distributions ?? []).map((d) =>
    d.distribution_type === 'vector_tiles'
      ? { ...d, url: vectorTileUrlForClients(d.url, visibility, publicApiBaseUrl) }
      : d,
  );

  if (distributions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        {t('distributions.noDistributions')}
      </p>
    );
  }

  const grouped = groupByType(distributions);

  const parquet = grouped.get('download')?.find((dist) => dist.format === 'parquet');

  return (
    <div className="space-y-5">
      {TYPE_ORDER.filter((type) => grouped.has(type)).map((type) => (
        <section key={type} aria-labelledby={`distributions-${type}`}>
          <h3 id={`distributions-${type}`} className="mb-1 text-sm font-medium">
            {t(TYPE_LABEL_KEYS[type])}
          </h3>
          <ul className="divide-y">
            {grouped.get(type)!.map((dist) => (
              <li key={dist.id} className="py-2">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                  <Badge variant="outline" className="text-xs">
                    {dist.format}
                  </Badge>
                  {dist.title && (
                    <span className="text-sm font-medium">{dist.title}</span>
                  )}
                  {dist.is_primary && (
                    <Badge variant="secondary" className="text-xs">
                      {t('distributions.primary')}
                    </Badge>
                  )}
                  {canEdit && !dist.auto_generated && (
                    <SetPrimaryControl
                      distribution={dist}
                      onSelect={(distributionId) => setPrimary.mutate(distributionId)}
                      isMutating={setPrimary.isPending}
                      isPendingThisRow={setPrimary.isPending && setPrimary.variables === dist.id}
                    />
                  )}
                  <CopyableUrl
                    distribution={dist}
                    publicApiUrl={publicApiBaseUrl}
                    datasetTitle={datasetTitle}
                    className="min-w-56 flex-1 basis-56"
                  />
                </div>
                {dist.description && (
                  <p className="mt-1 text-xs text-muted-foreground">{dist.description}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {parquet && <DuckDbHint distribution={parquet} datasetTitle={datasetTitle} />}
    </div>
  );
}

/** GeoParquet is lakehouse-native: a copy-paste DuckDB snippet makes the download queryable, not just archived. */
function DuckDbHint({
  distribution,
  datasetTitle,
}: {
  distribution: DistributionResponse;
  datasetTitle?: string;
}) {
  const { t } = useTranslation('dataset');
  const saved = distributionFilename(distribution, datasetTitle);
  // A single quote must be doubled to stay a valid DuckDB string literal.
  const file = saved.replace(/'/g, "''");
  const snippet = `INSTALL spatial; LOAD spatial;\nSELECT * FROM '${file}' LIMIT 10;`;

  return (
    <div className="rounded-md border bg-muted/30 p-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-mono text-2xs uppercase tracking-wide text-muted-foreground">
          {t('export.duckdbHint', { defaultValue: 'Query with DuckDB' })}
        </span>
        <CopyButton value={snippet} />
      </div>
      <pre className="overflow-x-auto text-2xs leading-5 text-foreground">
        <code>{snippet}</code>
      </pre>
    </div>
  );
}
