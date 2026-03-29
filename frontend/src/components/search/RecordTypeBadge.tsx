import { useTranslation } from 'react-i18next';
import { Combine, FolderOpen, Grid3X3, Layers, Table2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { recordTypeColors } from '@/lib/status-colors';

const TYPE_CONFIG = {
  vector_dataset: {
    icon: Layers,
    labelKey: 'card.vector',
  },
  raster_dataset: {
    icon: Grid3X3,
    labelKey: 'card.raster',
  },
  vrt_dataset: {
    icon: Combine,
    labelKey: 'card.vrt',
  },
  collection: {
    icon: FolderOpen,
    labelKey: 'card.collection',
  },
  table: {
    icon: Table2,
    labelKey: 'card.table',
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
  const colorClass = recordTypeColors[recordType] ?? recordTypeColors.unknown;

  return (
    <Badge
      variant="outline"
      className={`text-xs ${colorClass}${className ? ` ${className}` : ''}`}
    >
      <Icon className="size-3" />
      {t(config.labelKey)}
    </Badge>
  );
}
