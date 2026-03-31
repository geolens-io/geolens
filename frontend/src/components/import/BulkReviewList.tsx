import { useTranslation } from 'react-i18next';
import { Layers, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import type { FileEntry, CommitImportRequest } from '@/types/api';
import { isRasterPreview, isFilePreview } from './utils';
}

function getLayerName(entry: FileEntry): string | undefined {
  if (!entry.previewData || !isFilePreview(entry.previewData)) return undefined;
  const { layers, layer_name } = entry.previewData;
  return layers && layers.length > 1 ? layer_name : undefined;
}

function ReviewFormBlock({
  entry,
  isCommitting,
  onCommitSingle,
}: {
  entry: FileEntry;
  isCommitting: boolean;
  onCommitSingle: (entryId: string, request: CommitImportRequest) => void;
}) {
  const preview = entry.previewData!;
  const raster = isRasterPreview(preview);
  const file = isFilePreview(preview);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <ImportPreview preview={preview} />
      <ImportMetadataForm
        defaultName={preview.source_filename ?? entry.fileName}
        detectedCrs={raster ? preview.crs_epsg : (preview as FilePreviewResponse).crs}
        onCommit={(req) => {
          const layerName = getLayerName(entry);
          onCommitSingle(entry.id, layerName ? { ...req, layer_name: layerName } : req);
        }}
        isCommitting={isCommitting}
        isRaster={raster}
        previewData={raster ? preview : undefined}
        previewColumns={file ? (preview as FilePreviewResponse).columns : undefined}
        detectedGeometryColumns={file ? (preview as FilePreviewResponse).detected_geometry_columns : undefined}
      />
    </div>
  );
}

interface BulkReviewListProps {
  entries: FileEntry[];
  onCommitSingle: (entryId: string, request: CommitImportRequest) => void;
  onCommitAll: () => void;
  onCommitAllAsVrt?: () => void;
  onRemove: (entryId: string) => void;
  onSheetChange?: (entryId: string, layerName: string) => void;
  isCommitting: boolean;
}

export function BulkReviewList({
  entries,
  onCommitSingle,
  onCommitAll,
  onCommitAllAsVrt,
  onRemove,
  onSheetChange,
  isCommitting,
}: BulkReviewListProps) {
  const { t } = useTranslation('import');
  const readyCount = entries.filter((e) => e.status === 'preview').length;
  const rasterReadyCount = entries.filter(
    (e) => e.status === 'preview' && e.previewData && isRasterPreview(e.previewData),
  ).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">
          {t('bulk.fileCount', { count: readyCount })}
        </h3>
        <div className="flex items-center gap-2">
          {rasterReadyCount >= 2 && onCommitAllAsVrt && (
            <Button
              variant="secondary"
              onClick={onCommitAllAsVrt}
              disabled={readyCount === 0 || isCommitting}
            >
              <Layers className="mr-1 size-3" />
              {t('bulk.importAsVrt', { defaultValue: 'Import as VRT Mosaic' })}
            </Button>
          )}
          <Button
            onClick={onCommitAll}
            disabled={readyCount === 0 || isCommitting}
          >
            {t('bulk.importAllDefaults')}
          </Button>
        </div>
      </div>

      {entries.map((entry) => (
        <Card key={entry.id} className="p-4">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-medium">{entry.fileName}</span>
              {entry.status === 'tracking' && (
                <Badge
                  variant="outline"
                  className="bg-success/10 text-success border-success/30"
                >
                  {t('bulk.committed')}
                </Badge>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onRemove(entry.id)}
              disabled={entry.status === 'committing' || entry.status === 'tracking'}
              aria-label={t('bulk.removeFile')}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          {(entry.status === 'preview' || entry.status === 'committing') &&
            entry.previewData &&
            isFilePreview(entry.previewData) &&
            entry.previewData.layers &&
            entry.previewData.layers.length > 1 && (
              <div className="mb-4 space-y-1">
                <Label htmlFor={`sheet-${entry.id}`}>{t('bulk.sheetLabel', 'Sheet')}</Label>
                <select
                  id={`sheet-${entry.id}`}
                  value={entry.previewData.layer_name}
                  onChange={(e) => onSheetChange?.(entry.id, e.target.value)}
                  className="h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                >
                  {entry.previewData.layers.map((layer) => (
                    <option key={layer.name} value={layer.name}>
                      {layer.name} ({layer.feature_count} rows, {layer.field_count} columns)
                    </option>
                  ))}
                </select>
              </div>
            )}

          {(entry.status === 'preview' || entry.status === 'committing') &&
            entry.previewData && (
              <ReviewFormBlock
                entry={entry}
                isCommitting={entry.status === 'committing'}
                onCommitSingle={onCommitSingle}
              />
            )}

          {entry.status === 'commit-failed' && entry.previewData && (
            <div className="space-y-4">
              {entry.error && (
                <p className="text-sm text-destructive">{entry.error}</p>
              )}
              <ReviewFormBlock
                entry={entry}
                isCommitting={false}
                onCommitSingle={onCommitSingle}
              />
            </div>
          )}

          {entry.status === 'upload-failed' && entry.error && (
            <p className="text-sm text-destructive">{entry.error}</p>
          )}
        </Card>
      ))}
    </div>
  );
}
