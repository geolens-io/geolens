import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import type { FileEntry, CommitImportRequest, FilePreviewResponse, RasterPreviewResponse } from '@/types/api';

function isRasterPreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is RasterPreviewResponse {
  return 'band_count' in data;
}

function isFilePreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is FilePreviewResponse {
  return 'layers' in data || 'layer_name' in data;
}

interface BulkReviewListProps {
  entries: FileEntry[];
  onCommitSingle: (entryId: string, request: CommitImportRequest) => void;
  onCommitAll: () => void;
  onRemove: (entryId: string) => void;
  onSheetChange?: (entryId: string, layerName: string) => void;
  isCommitting: boolean;
}

export function BulkReviewList({
  entries,
  onCommitSingle,
  onCommitAll,
  onRemove,
  onSheetChange,
  isCommitting,
}: BulkReviewListProps) {
  const { t } = useTranslation('import');
  const readyCount = entries.filter((e) => e.status === 'preview').length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">
          {t('bulk.fileCount', { count: readyCount })}
        </h3>
        <Button
          onClick={onCommitAll}
          disabled={readyCount === 0 || isCommitting}
        >
          {t('bulk.importAllDefaults')}
        </Button>
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
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <ImportPreview preview={entry.previewData} />
                <ImportMetadataForm
                  defaultName={
                    entry.previewData.source_filename ?? entry.fileName
                  }
                  detectedCrs={
                    isRasterPreview(entry.previewData)
                      ? entry.previewData.crs_epsg
                      : entry.previewData.crs
                  }
                  onCommit={(req) => {
                    const hasMultiSheet = isFilePreview(entry.previewData!) && entry.previewData!.layers && entry.previewData!.layers.length > 1;
                    const layerName = hasMultiSheet && isFilePreview(entry.previewData!) ? (entry.previewData as FilePreviewResponse).layer_name : undefined;
                    onCommitSingle(entry.id, layerName ? { ...req, layer_name: layerName } : req);
                  }}
                  isCommitting={entry.status === 'committing'}
                  isRaster={isRasterPreview(entry.previewData)}
                  previewData={
                    isRasterPreview(entry.previewData)
                      ? entry.previewData
                      : undefined
                  }
                />
              </div>
            )}

          {entry.status === 'commit-failed' && entry.previewData && (
            <div className="space-y-4">
              {entry.error && (
                <p className="text-sm text-destructive">{entry.error}</p>
              )}
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <ImportPreview preview={entry.previewData} />
                <ImportMetadataForm
                  defaultName={
                    entry.previewData.source_filename ?? entry.fileName
                  }
                  detectedCrs={
                    isRasterPreview(entry.previewData)
                      ? entry.previewData.crs_epsg
                      : entry.previewData.crs
                  }
                  onCommit={(req) => {
                    const hasMultiSheet = isFilePreview(entry.previewData!) && entry.previewData!.layers && entry.previewData!.layers.length > 1;
                    const layerName = hasMultiSheet && isFilePreview(entry.previewData!) ? (entry.previewData as FilePreviewResponse).layer_name : undefined;
                    onCommitSingle(entry.id, layerName ? { ...req, layer_name: layerName } : req);
                  }}
                  isCommitting={false}
                  isRaster={isRasterPreview(entry.previewData)}
                  previewData={
                    isRasterPreview(entry.previewData)
                      ? entry.previewData
                      : undefined
                  }
                />
              </div>
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
