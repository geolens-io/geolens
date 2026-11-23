import { useTranslation } from 'react-i18next';
import { Box, ChartScatter, Combine, FolderOpen, Grid3X3, Layers, Table2 } from 'lucide-react';
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
  tiles3d_dataset: {
    icon: Box,
    labelKey: 'card.tiles3d',
  },
  pointcloud_dataset: {
    icon: ChartScatter,
    labelKey: 'card.pointcloud',
  },
} as const;

interface RecordTypeBadgeProps {
  recordType: string;
  className?: string;
  /** Icon only; the type name stays as the accessible name. */
  iconOnly?: boolean;
  /** Icon only and hidden from assistive technology, for beside a visible type name. */
  decorative?: boolean;
}

export function RecordTypeBadge({ recordType, className, iconOnly = false, decorative = false }: RecordTypeBadgeProps) {
  const { t } = useTranslation('search');

  const config = TYPE_CONFIG[recordType as keyof typeof TYPE_CONFIG];
  if (!config) return null;

  const Icon = config.icon;
  const colorClass = recordTypeColors[recordType] ?? recordTypeColors.unknown;

  const label = t(config.labelKey);

  if (decorative) {
    return (
      <Badge
        variant="outline"
        aria-hidden="true"
        className={`px-1.5 ${colorClass}${className ? ` ${className}` : ''}`}
      >
        <Icon className="size-3" />
      </Badge>
    );
  }

  return (
    <Badge
      variant="outline"
      className={`text-xs font-mono uppercase tracking-wider ${colorClass}${className ? ` ${className}` : ''}`}
      title={iconOnly ? label : undefined}
    >
      <Icon className="size-3" aria-hidden={iconOnly ? true : undefined} />
      {iconOnly ? <span className="sr-only">{label}</span> : label}
    </Badge>
  );
}
