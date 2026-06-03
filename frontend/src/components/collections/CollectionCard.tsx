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
  const isEmpty = collection.dataset_count === 0;
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
    <Card
      className={`flex flex-col gap-0 overflow-hidden py-0 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out sm:flex-row ${
        isEmpty
          ? 'border-dashed border-border/70 bg-muted/20 hover:border-border hover:bg-muted/30'
          : 'hover:border-primary/20 hover:bg-accent/50 hover:shadow-md'
      }`}
    >
      {/* Metadata section */}
      <div className="flex-1 p-4 min-w-0">
        <div className="flex items-start justify-between gap-3">
          <Link
            to={`/collections/${collection.id}`}
            className="line-clamp-1 text-lg font-semibold text-foreground transition-colors hover:text-primary"
          >
            {collection.name}
          </Link>
          {isEmpty && (
            <Badge variant="outline" className="shrink-0 border-dashed text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
              {t('card.emptyBadge', { defaultValue: 'Empty' })}
            </Badge>
          )}
        </div>

        {collection.description && (
          <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
            {collection.description}
          </p>
        )}
        {isEmpty && !collection.description && (
          <p className="mt-1.5 text-sm text-muted-foreground">
            {t('card.emptyHint', { defaultValue: 'This collection has no datasets yet.' })}
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
      <div className="sm:w-48 sm:flex-shrink-0 p-3 sm:p-4 sm:border-s border-t sm:border-t-0 border-border/50">
        <BBoxPreview bbox={bbox} />
      </div>
    </Card>
  );
}
