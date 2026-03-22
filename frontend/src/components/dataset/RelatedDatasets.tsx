import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { GitCompareArrows } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useRelatedDatasets } from '@/hooks/use-records';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { formatNumber } from '@/lib/format';

interface RelatedDatasetsProps {
  datasetId: string;
}

export function RelatedDatasets({ datasetId }: RelatedDatasetsProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, isError } = useRelatedDatasets(datasetId);

  if (isLoading || isError || !data || data.items.length === 0) {
    return null;
  }

  // Deduplicate items by dataset ID
  const uniqueItems = data.items.filter(
    (item, i, arr) => arr.findIndex((x) => x.id === item.id) === i,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <GitCompareArrows className="h-5 w-5" />
          {t('relatedDatasets.similarDatasets', { defaultValue: 'Similar datasets' })}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3 overflow-x-auto pb-1">
          {uniqueItems.map((item) => (
            <Link
              key={item.id}
              to={`/datasets/${item.id}`}
              className="block min-w-[180px] max-w-[220px] shrink-0 rounded-lg border p-3 transition-colors hover:bg-muted"
            >
              <p className="text-sm font-medium truncate" title={item.name}>
                {item.name}
              </p>
              <div className="mt-1.5 space-y-1">
                <RecordTypeBadge recordType={item.record_type ?? 'vector_dataset'} />
                {item.feature_count != null && (
                  <p className="text-xs text-muted-foreground">
                    {formatNumber(item.feature_count)} features
                  </p>
                )}
                {item.band_count != null && !item.feature_count && (
                  <p className="text-xs text-muted-foreground">
                    {item.band_count} bands
                  </p>
                )}
              </div>
              <span className="text-[10px] text-muted-foreground mt-1 block">
                {Math.round(item.similarity * 100)}% match
              </span>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
