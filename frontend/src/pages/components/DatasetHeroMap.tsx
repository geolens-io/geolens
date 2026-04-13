import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { DatasetMap } from '@/components/dataset/DatasetMap';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import type { DatasetResponse } from '@/types/api';
import type { HeroState } from '@/hooks/use-hero-state';

interface DatasetHeroMapProps {
  dataset: DatasetResponse;
  datasetId: string | undefined;
  bbox: [number, number, number, number] | null;
  isEditor: boolean;
  isDrawing: boolean;
  mapContainerRef: React.RefObject<HTMLDivElement | null>;
  onFeatureClick: (gid: number) => void;
  isRasterOrVrt: boolean;
  heroState: HeroState;
  retryCount: number;
  mapKey: number;
  handleRetry: () => void;
  onMapReady: () => void;
  onTileError: () => void;
}

export function DatasetHeroMap({
  dataset,
  datasetId,
  bbox,
  isEditor,
  isDrawing,
  mapContainerRef,
  onFeatureClick,
  isRasterOrVrt,
  heroState,
  retryCount,
  mapKey,
  handleRetry,
  onMapReady,
  onTileError,
}: DatasetHeroMapProps) {
  const { t } = useTranslation('dataset');
  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';

  return (
    <div
      ref={mapContainerRef}
      data-field-anchor="dataset_map"
      tabIndex={-1}
      className={cn(
        'rounded-lg border shadow-sm overflow-hidden relative',
        isDrawing ? 'h-[60vh]' : 'h-64 lg:h-80'
      )}
    >
      {isRasterOrVrt && heroState === 'loading' && (
        <Skeleton data-testid="hero-skeleton" className="absolute inset-0 z-10 rounded-lg" />
      )}
      <DatasetMap
        key={isRasterOrVrt ? mapKey : undefined}
        bbox={bbox}
        tableName={dataset.table_name}
        geometryType={dataset.geometry_type}
        datasetId={datasetId}
        columnInfo={dataset.column_info}
        containerRef={mapContainerRef}
        canEdit={isEditor && !isRaster && !isVrt && !isTable}
        recordType={dataset.record_type}
        rasterTileUrl={dataset.raster?.tile_url}
        tileVersion={dataset.updated_at}
        onFeatureClick={onFeatureClick}
        {...(isRasterOrVrt ? {
          onMapReady,
          onTileError,
        } : {})}
      />
      {dataset.record_type === 'raster_dataset' && !dataset.raster?.tile_url && heroState === 'loaded' && (
        <div className="absolute bottom-2 left-2 z-10 px-2 py-1 rounded bg-muted/80 text-xs text-muted-foreground">
          {t('raster.noTiles')}
        </div>
      )}
      {isRasterOrVrt && heroState === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/80 rounded-lg z-10">
          <AlertTriangle className="size-8 text-destructive mb-2" />
          <p className="text-sm text-muted-foreground mb-3">{t('raster.previewUnavailable')}</p>
          {retryCount < 3 ? (
            <Button size="sm" onClick={handleRetry}>{t('raster.retry')}</Button>
          ) : (
            <p className="text-xs text-muted-foreground">{t('raster.tilesProcessing')}</p>
          )}
        </div>
      )}
    </div>
  );
}
