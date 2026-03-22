import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Loader2, Search, FileX, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/layout/Pagination';
import { useCollectionDatasets } from '@/hooks/use-collections';
import { getGeometryTypeLabel } from '@/i18n/labels';


interface CollectionDatasetListProps {
  collectionId: string;
  onRemove?: (datasetId: string) => void;
}

const PAGE_SIZE = 20;

export function CollectionDatasetList({ collectionId, onRemove }: CollectionDatasetListProps) {
  const { t } = useTranslation('collections');
  const [skip, setSkip] = useState(0);
  const [filter, setFilter] = useState('');
  const { data, isLoading, error } = useCollectionDatasets(collectionId, skip, PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{t('datasetList.loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-center">
        <p className="text-sm text-destructive">
          {t('datasetList.errorMessage', { error: error.message })}
        </p>
      </div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
        <FileX className="size-10" />
        <p className="text-base font-medium">{t('datasetList.emptyTitle')}</p>
        <p className="text-sm">{t('datasetList.emptyDescription')}</p>
      </div>
    );
  }

  const filterLower = filter.toLowerCase();
  const filteredDatasets = filter
    ? data.datasets.filter((d) => d.title.toLowerCase().includes(filterLower))
    : data.datasets;

  return (
    <div className="space-y-4">
      {/* Filter input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder={t('datasetList.filterPlaceholder')}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Filtered results */}
      {filteredDatasets.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">
          {t('datasetList.noMatch', { filter })}
        </div>
      ) : (
        <div className="rounded-md border divide-y">
          {filteredDatasets.map((dataset) => (
            <div
              key={dataset.id}
              className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/50 transition-colors"
            >
              <Link
                to={`/datasets/${dataset.id}`}
                className="flex items-center justify-between gap-4 min-w-0 flex-1"
              >
                <span className="text-sm font-medium truncate min-w-0">
                  {dataset.title}
                </span>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {dataset.geometry_type && (
                    <Badge variant="outline" className="text-xs">
                      {getGeometryTypeLabel(t, dataset.geometry_type)}
                    </Badge>
                  )}
                  {dataset.feature_count !== null && dataset.feature_count !== undefined && (
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {t('datasetList.featureCount', { count: dataset.feature_count })}
                    </span>
                  )}
                </div>
              </Link>
              {onRemove && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 flex-shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => onRemove(dataset.id)}
                  title={t('datasetList.removeTitle')}
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {data.total > PAGE_SIZE && (
        <Pagination
          total={data.total}
          offset={skip}
          limit={PAGE_SIZE}
          onPageChange={(newOffset) => {
            setSkip(newOffset);
            setFilter('');
          }}
        />
      )}
    </div>
  );
}
