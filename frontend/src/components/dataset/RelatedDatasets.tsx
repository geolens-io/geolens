import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useRelatedDatasets } from '@/components/dataset/hooks/use-records';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';

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
      <CardHeader className="pb-2">
        <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {t('relatedDatasets.similarDatasets', { defaultValue: 'Similar datasets' })}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex flex-col gap-2">
          {uniqueItems.map((item) => (
            <Link
              key={item.id}
              to={`/datasets/${item.id}`}
              className="block rounded-lg border p-3 transition-colors hover:bg-muted"
            >
              <p className="text-sm font-medium truncate" title={item.name}>
                {item.name}
              </p>
              <div className="mt-1.5 space-y-1">
                <RecordTypeBadge recordType={item.record_type ?? 'vector_dataset'} />
                {item.feature_count != null && (
                  <p className="text-xs text-muted-foreground">
                    {t('relatedDatasets.featureCount', { count: item.feature_count, defaultValue: '{{count}} features' })}
                  </p>
                )}
                {item.band_count != null && !item.feature_count && (
                  <p className="text-xs text-muted-foreground">
                    {item.band_count} bands
                  </p>
                )}
              </div>
              <span className="text-[10px] text-muted-foreground mt-1 block">
                {t('relatedDatasets.similarityMatch', { percent: Math.round(item.similarity * 100), defaultValue: '{{percent}}% match' })}
              </span>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
