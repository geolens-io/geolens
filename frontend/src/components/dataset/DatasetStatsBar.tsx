import { useTranslation } from 'react-i18next';
import { formatNumber, formatRelativeDate } from '@/lib/format';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { computeRasterGsd } from '@/lib/geo-utils';
import type { DatasetResponse } from '@/types/api';
import { cn } from '@/lib/utils';

interface StatCellProps {
  label: string;
  value: string;
  mono?: boolean;
}

function StatCell({ label, value, mono }: StatCellProps) {
  return (
    <div className="px-4 py-3 border-r border-border last:border-r-0 min-w-0">
      <div className="text-[10.5px] font-mono uppercase tracking-widest text-muted-foreground mb-1">
        {label}
      </div>
      <div
        className={cn(
          'text-[15px] font-medium truncate',
          mono && 'font-mono text-sm tracking-wide',
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

interface DatasetStatsBarProps {
  dataset: DatasetResponse;
  className?: string;
}

export function DatasetStatsBar({ dataset, className }: DatasetStatsBarProps) {
  const { t } = useTranslation('dataset');

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';

  const rasterGsd = computeRasterGsd(dataset.raster?.res_x, dataset.raster?.res_y);

  const cells: StatCellProps[] = [];

  if (isRaster || isVrt) {
    // Raster/VRT stats
    if (dataset.raster?.band_count != null) {
      cells.push({
        label: t('raster.bands', { defaultValue: 'Bands' }),
        value: String(dataset.raster.band_count),
      });
    }
    if (rasterGsd != null) {
      cells.push({
        label: t('raster.resolution', { defaultValue: 'Resolution' }),
        value: `${rasterGsd} m`,
        mono: true,
      });
    }
    if (dataset.raster?.epsg) {
      cells.push({
        label: t('overview.crs', { defaultValue: 'CRS' }),
        value: `EPSG:${dataset.raster.epsg}`,
        mono: true,
      });
    }
    if (isVrt && dataset.raster?.source_count != null) {
      cells.push({
        label: t('metadata.sourceCount', { defaultValue: 'Sources' }),
        value: String(dataset.raster.source_count),
      });
    }
  } else {
    // Vector/Table stats
    if (dataset.feature_count != null) {
      cells.push({
        label: isTable
          ? t('metadata.rows', { defaultValue: 'Rows' })
          : t('metadata.features', { defaultValue: 'Features' }),
        value: formatNumber(dataset.feature_count),
      });
    }
    if (dataset.geometry_type) {
      cells.push({
        label: t('metadata.geometry', { defaultValue: 'Geometry' }),
        value: getGeometryTypeLabel(t, dataset.geometry_type),
        mono: true,
      });
    }
    if (dataset.srid) {
      cells.push({
        label: t('overview.crs', { defaultValue: 'CRS' }),
        value: `EPSG:${dataset.srid}`,
        mono: true,
      });
    }
    if (dataset.current_version != null) {
      cells.push({
        label: t('metadata.version', { defaultValue: 'Version' }),
        value: `v${dataset.current_version}`,
        mono: true,
      });
    }
    if (dataset.column_info) {
      cells.push({
        label: t('metadata.columns', { defaultValue: 'Columns' }),
        value: String(dataset.column_info.length),
      });
    }
  }

  // Updated — always shown
  cells.push({
    label: t('metadata.updated', { defaultValue: 'Updated' }),
    value: formatRelativeDate(dataset.updated_at),
  });

  // Limit to 6 cells max
  const displayCells = cells.slice(0, 6);

  return (
    <div
      className={cn(
        'grid border-y border-border',
        className,
      )}
      style={{ gridTemplateColumns: `repeat(${displayCells.length}, 1fr)` }}
    >
      {displayCells.map((cell) => (
        <StatCell key={cell.label} {...cell} />
      ))}
    </div>
  );
}
