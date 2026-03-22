import { useTranslation } from 'react-i18next';
import type { FilePreviewResponse, RasterPreviewResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { getGeometryTypeLabel } from '@/i18n/labels';

interface ImportPreviewProps {
  preview: FilePreviewResponse | RasterPreviewResponse;
}

function isRasterPreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is RasterPreviewResponse {
  return 'band_count' in data;
}

const MAX_VISIBLE_COLUMNS = 8;

export function ImportPreview({ preview }: ImportPreviewProps) {
  const { t } = useTranslation('import');

  // Raster preview
  if (isRasterPreview(preview)) {
    return (
      <Card className="p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Badge
            variant="secondary"
            className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
          >
            Raster
          </Badge>
          <span className="text-sm font-medium">{preview.source_filename}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
          <div>
            <span className="text-muted-foreground">CRS:</span>{' '}
            {preview.crs_epsg ? `EPSG:${preview.crs_epsg}` : 'Unknown'}
          </div>
          <div>
            <span className="text-muted-foreground">Bands:</span> {preview.band_count}
          </div>
          <div>
            <span className="text-muted-foreground">Size:</span> {preview.width} x{' '}
            {preview.height} px
          </div>
          <div>
            <span className="text-muted-foreground">Type:</span> {preview.dtype}
          </div>
          <div>
            <span className="text-muted-foreground">Resolution:</span>{' '}
            {preview.res_x.toFixed(6)} x {preview.res_y.toFixed(6)}
          </div>
          <div>
            <span className="text-muted-foreground">COG:</span>{' '}
            {preview.is_cog_compliant ? 'Valid COG' : 'Will convert'}
          </div>
          {preview.temporal_start && (
            <div>
              <span className="text-muted-foreground">Date:</span>{' '}
              {preview.temporal_start}
            </div>
          )}
        </div>
        {!preview.is_cog_compliant && (
          <p className="text-xs text-muted-foreground">{preview.compliance_reason}</p>
        )}
      </Card>
    );
  }

  // Vector preview
  const visibleColumns = preview.columns.slice(0, MAX_VISIBLE_COLUMNS);
  const extraCount = preview.columns.length - MAX_VISIBLE_COLUMNS;
  const hasSampleData =
    preview.columns.length > 0 && preview.sample_rows.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('preview.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Metadata grid */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">{t('preview.crs')}</p>
            <Badge variant="secondary">
              {preview.crs ? `EPSG:${preview.crs}` : t('preview.unknown')}
            </Badge>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t('preview.geometryType')}</p>
            <Badge variant="secondary">
              {preview.geometry_type
                ? getGeometryTypeLabel(t, preview.geometry_type)
                : t('preview.none')}
            </Badge>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t('preview.featureCount')}</p>
            <Badge variant="secondary">
              {preview.feature_count !== null
                ? preview.feature_count.toLocaleString()
                : t('preview.unknown')}
            </Badge>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t('preview.layerName')}</p>
            <Badge variant="secondary">{preview.layer_name}</Badge>
          </div>
        </div>

        {/* Sample data table */}
        {hasSampleData ? (
          <div>
            <p className="mb-2 text-sm font-medium">
              {t('preview.sampleData')}
              {extraCount > 0 && (
                <span className="ml-2 text-xs text-muted-foreground">
                  {t('preview.moreColumns', { count: extraCount })}
                </span>
              )}
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {visibleColumns.map((col) => (
                      <TableHead key={col.name} className="whitespace-nowrap">
                        {col.name}
                        <span className="ml-1 font-normal text-muted-foreground">
                          ({col.type})
                        </span>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.sample_rows.map((row, i) => (
                    <TableRow key={i}>
                      {visibleColumns.map((col) => (
                        <TableCell
                          key={col.name}
                          className="max-w-[200px] truncate whitespace-nowrap"
                        >
                          {row[col.name] !== null && row[col.name] !== undefined
                            ? String(row[col.name])
                            : ''}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t('preview.noSampleData')}</p>
        )}
      </CardContent>
    </Card>
  );
}
