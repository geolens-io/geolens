import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';

interface DatasetCollectionBadgesProps {
  collections: Array<{ id: string; name: string }> | null;
}

export function DatasetCollectionBadges({ collections }: DatasetCollectionBadgesProps) {
  const { t } = useTranslation('collections');
  if (!collections || collections.length === 0) return null;

  return (
    <div className="space-y-2">
      <span className="text-sm font-medium text-muted-foreground">{t('badges.label')}</span>
      <div className="flex flex-wrap gap-1.5">
        {collections.map((coll) => (
          <Link key={coll.id} to={`/collections/${coll.id}`}>
            <Badge variant="secondary" className="hover:bg-secondary/80 cursor-pointer">
              {coll.name}
            </Badge>
          </Link>
        ))}
      </div>
    </div>
  );
}
