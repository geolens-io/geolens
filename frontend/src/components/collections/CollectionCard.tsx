import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BBoxPreview } from '@/components/layout/BBoxPreview';
import { formatDate } from '@/lib/format';
import type { CollectionResponse } from '@/types/api';

interface CollectionCardProps {
  collection: CollectionResponse;
}

export function CollectionCard({ collection }: CollectionCardProps) {
  const { t } = useTranslation('collections');
  const bbox =
    collection.extent_bbox && collection.extent_bbox.length >= 4
      ? (collection.extent_bbox as [number, number, number, number])
      : null;

  const formatTemporal = (): string | null => {
    if (!collection.temporal_start && !collection.temporal_end) return null;
    const start = collection.temporal_start
      ? formatDate(collection.temporal_start)
      : '...';
    const end = collection.temporal_end
      ? formatDate(collection.temporal_end)
      : t('card.temporalPresent');
    return `${start} - ${end}`;
  };

  const temporal = formatTemporal();

  return (
    <Card className="flex flex-col sm:flex-row gap-0 py-0 overflow-hidden hover:shadow-md hover:border-primary/20 hover:bg-accent/50 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out">
      {/* Metadata section */}
      <div className="flex-1 p-4 min-w-0">
        <Link
          to={`/collections/${collection.id}`}
          className="text-lg font-semibold text-foreground hover:text-primary transition-colors line-clamp-1"
        >
          {collection.name}
        </Link>

        {collection.description && (
          <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
            {collection.description}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="text-xs">
            {t('card.datasetCount', { count: collection.dataset_count })}
          </Badge>
          {temporal && (
            <span className="text-xs text-muted-foreground">{temporal}</span>
          )}
          <span className="text-xs text-muted-foreground">
            {t('card.created', { date: formatDate(collection.created_at) })}
          </span>
        </div>
      </div>

      {/* BBox preview section */}
      <div className="sm:w-48 sm:flex-shrink-0 p-3 sm:p-4 sm:border-l border-t sm:border-t-0 border-border/50">
        <BBoxPreview bbox={bbox} />
      </div>
    </Card>
  );
}
