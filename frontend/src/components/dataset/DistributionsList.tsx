import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  useDistributions,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Copy, Check, Circle, CircleDot, Loader2, Download } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import {
  getPublicApiBaseUrl,
  resolveDistributionUrl,
  isAbsoluteUrl,
} from '@/lib/dataset-access';
import { authenticatedDownload } from '@/api/datasets';
import type { DistributionResponse } from '@/types/api';

interface DistributionsListProps {
  recordId: string;
  /** Owner-or-admin editor: mirrors the backend `require_permission("edit_metadata")`
   * + `_check_record_ownership` guard on the distribution PATCH endpoint.
   * Everyone else keeps the read-only view (#1395). */
  canEdit?: boolean;
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

function CopyableUrl({
  distribution,
  publicApiUrl,
}: {
  distribution: DistributionResponse;
  publicApiUrl: string | null | undefined;
}) {
  const { t } = useTranslation('dataset');
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const resolvedUrl = resolveDistributionUrl(distribution.url, publicApiUrl);
  // fix(#1863 P1): resolveDistributionUrl only prefixes a RELATIVE url with
  // the API base — an already-absolute url (a manual distribution, e.g. an
  // external viewer app) passes through unchanged and is not a GeoLens API
  // resource, so it must never receive this session's bearer token.
  const isSameOriginApiResource = !isAbsoluteUrl(distribution.url);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(resolvedUrl);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = resolvedUrl;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  }

  // fix(#1863 P1): a plain <a href download> browser navigation carries no
  // Authorization header, so a private or unpublished dataset's export
  // endpoint rejected it as anonymous. Route same-origin GeoLens resources
  // through the same refresh-aware, bearer-authenticated fetch-and-save flow
  // ExportButton already uses (api/datasets.ts's authenticatedDownload).
  async function handleAuthenticatedDownload() {
    if (downloading) return;
    setDownloading(true);
    try {
      const base = (distribution.title?.trim() || distribution.distribution_type).replace(/[/\\]/g, '_');
      await authenticatedDownload(resolvedUrl, `${base}.${distribution.format}`);
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
    <div className="flex items-center gap-2">
      <code className="flex-1 rounded-sm bg-muted px-2 py-1.5 font-mono text-xs text-foreground truncate" title={resolvedUrl}>
        {resolvedUrl}
      </code>
      {/* fix(#1856): these were copyable text with no way to actually fetch
          the resource. Same-origin GeoLens resources download through the
          authenticated fetch flow (needed for private/unpublished datasets);
          an external URL from a manual distribution is a plain link instead
          — it is not ours to attach a bearer token to. */}
      {isSameOriginApiResource ? (
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
      )}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        onClick={handleCopy}
        aria-label={t('distributions.copyUrl')}
        title={t('distributions.copyUrl')}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}

/** fix(#1395 codex round 3): title alone can collide — `uq_record_distribution`
 * covers (record_id, distribution_type, format, url), not title, so two
 * manual rows are free to share one, and a truncated URL is only unique
 * up to whatever the truncation cuts off (round 2's fix). The row's own
 * `id` is the one field the database actually guarantees is unique — use it
 * untruncated instead of a heuristic. */
function distributionLabel(distribution: DistributionResponse): string {
  const base =
    distribution.title?.trim() || distribution.format || distribution.distribution_type;
  return `${base} (${distribution.id})`;
}

/** feat(#1395): radio-style set-primary control. Rendered only for manual
 * (non-auto_generated) rows — `update_distribution` rejects any write,
 * `is_primary` included, against an auto_generated row with a 400, so a
 * control on those rows could never do anything but fail. The currently
 * primary manual row renders checked and disabled; clicking any other one
 * PATCHes it to `is_primary: true`, which the backend applies as a
 * last-write-wins demote of every other row on the record (#1383).
 *
 * fix(#1395 codex round 1): `isMutating` disables every sibling control
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

export function DistributionsList({ recordId, canEdit = false }: DistributionsListProps) {
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

  const distributions = data?.distributions ?? [];

  if (distributions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        {t('distributions.noDistributions')}
      </p>
    );
  }

  const grouped = groupByType(distributions);

  return (
    <div className="space-y-4">
      {TYPE_ORDER.filter((type) => grouped.has(type)).map((type) => (
        <Card key={type}>
          <CardHeader className="pb-3">
            <CardTitle level={3} className="text-sm">{t(TYPE_LABEL_KEYS[type])}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {grouped.get(type)!.map((dist) => (
              <div key={dist.id} className="space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="text-xs">
                    {dist.format}
                  </Badge>
                  {dist.is_primary && (
                    <Badge variant="secondary" className="text-xs">
                      {t('distributions.primary')}
                    </Badge>
                  )}
                  {dist.auto_generated && (
                    <span className="text-xs text-muted-foreground">
                      ({t('distributions.auto')})
                    </span>
                  )}
                  {canEdit && !dist.auto_generated && (
                    <SetPrimaryControl
                      distribution={dist}
                      onSelect={(distributionId) => setPrimary.mutate(distributionId)}
                      isMutating={setPrimary.isPending}
                      isPendingThisRow={setPrimary.isPending && setPrimary.variables === dist.id}
                    />
                  )}
                </div>
                {dist.title && (
                  <p className="text-sm font-medium">{dist.title}</p>
                )}
                {dist.description && (
                  <p className="text-xs text-muted-foreground">{dist.description}</p>
                )}
                <CopyableUrl distribution={dist} publicApiUrl={publicApiBaseUrl} />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
