import { useTranslation } from 'react-i18next';
import { Combine, FolderOpen, Grid3X3, Layers } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

const TYPE_CONFIG = {
  vector_dataset: {
    icon: Layers,
    labelKey: 'card.vector',
    className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  raster_dataset: {
    icon: Grid3X3,
    labelKey: 'card.raster',
    className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  vrt_dataset: {
    icon: Combine,
    labelKey: 'card.vrt',
    className: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400',
  },
  collection: {
    icon: FolderOpen,
    labelKey: 'card.collection',
    className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
} as const;

interface RecordTypeBadgeProps {
  recordType: string;
  className?: string;
}

export function RecordTypeBadge({ recordType, className }: RecordTypeBadgeProps) {
  const { t } = useTranslation('search');

  const config = TYPE_CONFIG[recordType as keyof typeof TYPE_CONFIG];
  if (!config) return null;

  const Icon = config.icon;

  return (
    <Badge
      variant="secondary"
      className={`text-xs ${config.className}${className ? ` ${className}` : ''}`}
    >
      <Icon className="size-3" />
      {t(config.labelKey)}
    </Badge>
  );
}
