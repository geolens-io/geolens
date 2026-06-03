import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Copy, Check } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import {
  getPublicApiBaseUrl,
  resolveDistributionUrl,
} from '@/lib/dataset-access';
import type { DistributionResponse } from '@/types/api';

interface DistributionsListProps {
  recordId: string;
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

function CopyableUrl({ url, publicApiUrl }: { url: string; publicApiUrl: string | null | undefined }) {
  const { t } = useTranslation('dataset');
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const resolvedUrl = resolveDistributionUrl(url, publicApiUrl);

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

  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 rounded bg-muted px-2 py-1.5 font-mono text-xs text-foreground truncate" title={resolvedUrl}>
        {resolvedUrl}
      </code>
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

export function DistributionsList({ recordId }: DistributionsListProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, error } = useDistributions(recordId);
  const { data: tileConfig } = useTileConfig();
  const publicApiBaseUrl = getPublicApiBaseUrl(tileConfig);

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
            <CardTitle className="text-sm">{t(TYPE_LABEL_KEYS[type])}</CardTitle>
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
                </div>
                {dist.title && (
                  <p className="text-sm font-medium">{dist.title}</p>
                )}
                {dist.description && (
                  <p className="text-xs text-muted-foreground">{dist.description}</p>
                )}
                <CopyableUrl url={dist.url} publicApiUrl={publicApiBaseUrl} />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
