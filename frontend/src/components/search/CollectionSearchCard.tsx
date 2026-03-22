import { Link } from 'react-router';
import { FolderOpen } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useTranslation } from 'react-i18next';
import { RecordTypeBadge } from './RecordTypeBadge';

interface CollectionSearchCardProps {
  id: string;
  title: string;
  description: string | null;
  datasetCount: number;
}

export function CollectionSearchCard({ id, title, description, datasetCount }: CollectionSearchCardProps) {
  const { t } = useTranslation('search');

  return (
    <Link
      to={`/collections/${id}`}
      className="group block rounded-lg border bg-card p-3 transition-colors hover:border-primary/50 hover:bg-accent/50"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-muted p-1.5">
          <FolderOpen className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium leading-tight group-hover:text-primary truncate">
              {title}
            </h3>
            <Badge variant="secondary" className="shrink-0 text-xs">
              {t('collection.datasetCount', { count: datasetCount, defaultValue: '{{count}} datasets' })}
            </Badge>
            <RecordTypeBadge recordType="collection" />
          </div>
          {description && (
            <p className="text-sm text-muted-foreground line-clamp-2">{description}</p>
          )}
        </div>
      </div>
    </Link>
  );
}
