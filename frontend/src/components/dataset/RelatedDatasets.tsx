import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useRelatedDatasets } from '@/components/dataset/hooks/use-records';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { SECTION_EYEBROW } from '@/components/dataset/SectionEyebrow';

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
    <Card className="gap-2 py-4">
      <CardHeader className="pb-2">
        <CardTitle level={2} className={SECTION_EYEBROW}>
          {t('relatedDatasets.similarDatasets', { defaultValue: 'Similar datasets' })}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Grid so cards sit 2-up below lg (where the rail unstacks to full width)
            and 1-up inside the 300px rail at lg+, keeping the section compact. */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-2">
          {uniqueItems.map((item) => (
            <Link
              key={item.id}
              to={`/datasets/${item.id}`}
              className="block rounded-lg border p-2.5 transition-colors hover:bg-muted"
            >
              <p className="text-sm font-medium truncate" title={item.name}>
                {item.name}
              </p>
              <div className="mt-1.5 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                <RecordTypeBadge recordType={item.record_type ?? 'vector_dataset'} />
                {item.feature_count != null && (
                  <span>{t('relatedDatasets.featureCount', { count: item.feature_count, defaultValue: '{{count}} features' })}</span>
                )}
                {item.band_count != null && !item.feature_count && (
                  <span>{item.band_count} bands</span>
                )}
                <span className="ms-auto text-mini">
                  {t('relatedDatasets.similarityMatch', { percent: Math.round(item.similarity * 100), defaultValue: '{{percent}}% match' })}
                </span>
              </div>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
