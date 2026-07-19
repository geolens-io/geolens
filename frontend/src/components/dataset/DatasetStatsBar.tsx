import { useTranslation } from 'react-i18next';
import { formatGsd, formatNumber, formatRelativeDate } from '@/lib/format';
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
    // #305: cell borders drawn on top/left so they read correctly
    // whether cells sit in one desktop row or wrap onto multiple mobile rows.
    <div className="px-4 py-3 border-t border-l border-border min-w-0">
      <div className="text-mini font-mono uppercase tracking-widest text-muted-foreground mb-1">
        {label}
      </div>
      <div
        className={cn(
          'text-base font-medium truncate',
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
  const { t, i18n } = useTranslation('dataset');

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
        // fix(#569): res_x/res_y are CRS units — a geographic CRS delivers
        // degrees, which must not be labeled meters.
        value: formatGsd(
          rasterGsd,
          {
            isGeographic: dataset.raster?.crs_is_geographic,
            crs: dataset.raster?.epsg != null ? `EPSG:${dataset.raster.epsg}` : null,
          },
          i18n.language,
        ),
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

  // #305: reflow responsively so stats never get crushed/truncated on small
  // screens, and cap columns to the number of rendered cells at every
  // breakpoint so a sparse dataset (1-2 stats) leaves no empty grid columns.
  const gridColsClass: Record<number, string> = {
    1: 'grid-cols-1',
    2: 'grid-cols-2',
    3: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-3',
    4: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4',
    5: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-5',
    6: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-6',
  };

  return (
    <div
      className={cn(
        // Outer right/bottom borders complete the frame the per-cell top/left
        // borders start, keeping the desktop row visually equivalent to before.
        'grid border-r border-b border-border',
        gridColsClass[displayCells.length] ?? 'grid-cols-2 sm:grid-cols-3 md:grid-cols-6',
        className,
      )}
    >
      {displayCells.map((cell) => (
        <StatCell key={cell.label} {...cell} />
      ))}
    </div>
  );
}
