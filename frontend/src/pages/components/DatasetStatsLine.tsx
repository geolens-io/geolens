import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, ShieldAlert } from 'lucide-react';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { visibilityColors } from '@/lib/status-colors';
import { formatRelativeDate, formatNumber } from '@/lib/format';
import { getRecordStatusLabel, getGeometryTypeLabel } from '@/i18n/labels';
import type { DatasetResponse } from '@/types/api';

const Sep = () => <span className="text-muted-foreground/50">·</span>;

interface DatasetStatsLineProps {
  dataset: DatasetResponse;
  rasterGsd: number | null;
}

export function DatasetStatsLine({ dataset, rasterGsd }: DatasetStatsLineProps) {
  const { t } = useTranslation('dataset');
  const isTable = dataset.record_type === 'table';

  return (
    <>
      <div className="flex items-center gap-1.5 flex-wrap">
        <RecordTypeBadge recordType={dataset.record_type} />
        {dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type ? (
          <>
            {dataset.geometry_type && (
              <>
                <Sep />
                <span>{getGeometryTypeLabel(t, dataset.geometry_type)}</span>
              </>
            )}
            {dataset.feature_count != null && (
              <>
                <Sep />
                <span>{formatNumber(dataset.feature_count)} {isTable ? 'rows' : 'features'}</span>
              </>
            )}
            {dataset.srid && (
              <>
                <Sep />
                <span>EPSG:{dataset.srid}</span>
              </>
            )}
            {dataset.is_3d && (
              <>
                <Sep />
                <span className="font-medium">3D</span>
                {dataset.z_min != null && dataset.z_max != null && (
                  <span className="ml-1 text-muted-foreground">
                    Z: {dataset.z_min.toFixed(1)} to {dataset.z_max.toFixed(1)}
                  </span>
                )}
              </>
            )}
          </>
        ) : dataset.record_type === 'raster_dataset' ? (
          <>
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} {t('raster.bands').toLowerCase()}</span>
              </>
            )}
            {rasterGsd != null && (
              <>
                <Sep />
                <span>{rasterGsd} m</span>
              </>
            )}
            {dataset.raster?.epsg && (
              <>
                <Sep />
                <span>EPSG:{dataset.raster.epsg}</span>
              </>
            )}
          </>
        ) : dataset.record_type === 'vrt_dataset' ? (
          <>
            {dataset.raster?.vrt_type && (
              <>
                <Sep />
                <span>{dataset.raster.vrt_type === 'band_stack' ? t('raster.bandStack') : t('raster.mosaic')}</span>
              </>
            )}
            {dataset.raster?.source_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.source_count} sources</span>
              </>
            )}
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} bands</span>
              </>
            )}
            {dataset.raster?.epsg && (
              <>
                <Sep />
                <span>EPSG:{dataset.raster.epsg}</span>
              </>
            )}
          </>
        ) : null}
      </div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>{getRecordStatusLabel(t, dataset.record_status)}</span>
        <Sep />
        <Badge variant="outline" className={cn('text-xs capitalize', visibilityColors[dataset.visibility] ?? '')}>
          {dataset.visibility === 'public' ? <Eye className="me-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="me-1 h-3 w-3" /> : <EyeOff className="me-1 h-3 w-3" />}
          {dataset.visibility}
        </Badge>
        <Sep />
        <span>Updated {formatRelativeDate(dataset.updated_at)}</span>
      </div>
    </>
  );
}
