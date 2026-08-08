import { Database, Globe, Satellite, SquarePen, Upload, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { DatasetOrigin } from '@/types/api';

// feat(#1218): the union moved to types/api.ts, where the backend now serves it
// as the computed `origin` field. Re-exported here so existing importers keep
// working and the vocabulary keeps one definition.
export type { DatasetOrigin };

const SERVICE_FORMATS = new Set(['wfs', 'arcgis_featureserver', 'ogcapi_features']);

/**
 * Derive the origin from persisted source fields.
 *
 * Register Table keeps an existing table in GeoLens's own PostGIS database
 * in place and stores no `source_format` (see backend
 * `register_existing_table`), so null identifies that source mode. VRTs also
 * store null but are composed from other datasets, and collections have no
 * dataset row — both return null so the type badge speaks for them alone.
 */
export function datasetOrigin(input: {
  source_format?: string | null;
  record_type?: string | null;
}): DatasetOrigin | null {
  const recordType = input.record_type ?? 'vector_dataset';
  if (recordType === 'collection' || recordType === 'vrt_dataset') return null;
  const format = input.source_format;
  if (!format) return 'postgis';
  if (format === 'created') return 'created';
  if (format === 'stac') return 'stac';
  if (SERVICE_FORMATS.has(format)) return 'service';
  return 'upload';
}

const ORIGIN_ICONS: Record<DatasetOrigin, LucideIcon> = {
  upload: Upload,
  postgis: Database,
  service: Globe,
  stac: Satellite,
  created: SquarePen,
};

interface OriginBadgeProps {
  origin: DatasetOrigin;
  className?: string;
}

/**
 * Mono-caps origin chip. Icons match the Import page's mode tabs so the
 * vocabulary stays consistent from ingest to catalog.
 */
export function OriginBadge({ origin, className }: OriginBadgeProps) {
  const { t } = useTranslation();
  const Icon = ORIGIN_ICONS[origin];

  return (
    <Badge
      variant="outline"
      data-testid="origin-badge"
      data-origin={origin}
      title={t(`origin.${origin}.title`)}
      className={cn(
        'gap-1 border-border/70 bg-surface-2/60 font-mono text-2xs font-medium uppercase tracking-[0.08em] text-muted-foreground',
        className,
      )}
    >
      <Icon aria-hidden="true" />
      {t(`origin.${origin}.label`)}
    </Badge>
  );
}
