import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Layers, X, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { ImportMetadataForm } from './ImportMetadataForm';
import { TypeTag } from './TypeTag';
import { StatusPill } from './StatusPill';
import { isRasterPreview, isFilePreview, fileExt, kindFromEntry } from './utils';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { formatNumber } from '@/lib/format';
import type { FileEntry, CommitImportRequest, FilePreviewResponse } from '@/types/api';

/* ── Detection panel (expanded row) ──────────────────── */

function DetectionPanel({ entry }: { entry: FileEntry }) {
  const { t } = useTranslation('import');
  const preview = entry.previewData;
  if (!preview) return null;

  const raster = isRasterPreview(preview);
  const file = isFilePreview(preview) ? preview : null;

  return (
    <div className="col-span-full mt-3 grid gap-5 border-t border-dashed border-border pt-4 md:grid-cols-2">
      {/* Geometry & projection */}
      <div>
        <h5 className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {raster ? t('detect.rasterInfo', { defaultValue: 'Raster info' }) : t('detect.geometry', { defaultValue: 'Geometry & projection' })}
        </h5>
        <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-1 text-xs">
          {raster ? (
            <>
              <dt className="font-mono text-[11px] text-muted-foreground">bands</dt>
              <dd className="font-mono text-[11.5px]">{preview.band_count}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">size</dt>
              <dd className="font-mono text-[11.5px]">{preview.width} x {preview.height} px</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">dtype</dt>
              <dd className="font-mono text-[11.5px]">{preview.dtype}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">crs</dt>
              <dd className="font-mono text-[11.5px]">{preview.crs_epsg ? `EPSG:${preview.crs_epsg}` : 'Unknown'}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">COG</dt>
              <dd className="font-mono text-[11.5px]">
                {preview.is_cog_compliant
                  ? <span className="text-success">{t('detect.validCog', { defaultValue: 'Valid' })}</span>
                  : <span className="text-warning-foreground">{t('detect.willConvert', { defaultValue: 'Will convert' })}</span>}
              </dd>
            </>
          ) : file ? (
            <>
              <dt className="font-mono text-[11px] text-muted-foreground">type</dt>
              <dd className="font-mono text-[11.5px]">
                {file.geometry_type ? getGeometryTypeLabel(t, file.geometry_type) : t('detect.nonSpatial', { defaultValue: 'Non-spatial' })}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">features</dt>
              <dd className="font-mono text-[11.5px]">
                {file.feature_count != null ? formatNumber(file.feature_count) : '—'}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">crs</dt>
              <dd className="font-mono text-[11.5px]">
                {file.crs ? `EPSG:${file.crs}` : '—'}
                {file.crs && file.crs !== 4326 && file.crs !== 3857 && (
                  <span className="ms-1 text-muted-foreground">→ will reproject on read</span>
                )}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">layer</dt>
              <dd className="font-mono text-[11.5px]">{file.layer_name}</dd>
            </>
          ) : null}
        </dl>
      </div>

      {/* Schema columns */}
      {file && file.columns.length > 0 && (
        <div>
          <h5 className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
            {t('detect.schema', { defaultValue: 'Schema' })} · {file.columns.length} columns
          </h5>
          <div className="max-h-44 overflow-y-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface-0">
                  <th className="px-2 py-1.5 text-start font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Column</th>
                  <th className="px-2 py-1.5 text-start font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Type</th>
                </tr>
              </thead>
              <tbody>
                {file.columns.slice(0, 12).map((col) => (
                  <tr key={col.name} className="border-b border-border last:border-0">
                    <td className="px-2 py-1 font-mono text-[11.5px]">{col.name}</td>
                    <td className="px-2 py-1">
                      <span className={cn(
                        'inline-block rounded px-1.5 py-px font-mono text-[10.5px]',
                        col.type.toLowerCase().includes('geom')
                          ? 'bg-type-vector-bg text-type-vector'
                          : 'bg-surface-2 text-muted-foreground',
                      )}>
                        {col.type}
                      </span>
                    </td>
                  </tr>
                ))}
                {file.columns.length > 12 && (
                  <tr>
                    <td colSpan={2} className="px-2 py-1 text-center text-[11px] text-muted-foreground">
                      +{file.columns.length - 12} more
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Metadata form wrapper ───────────────────────────── */

function ReviewFormBlock({
  entry,
  isCommitting,
  onCommitSingle,
}: {
  entry: FileEntry;
  isCommitting: boolean;
  onCommitSingle: (entryId: string, request: CommitImportRequest) => void;
}) {
  const preview = entry.previewData;
  if (!preview) return null;

  const raster = isRasterPreview(preview);
  const fp = isFilePreview(preview) ? preview : null;

  function getLayerName(): string | undefined {
    if (!fp?.layers || fp.layers.length <= 1) return undefined;
    return fp.layer_name;
  }

  return (
    <div className="col-span-full border-t border-border pt-4 mt-2">
      <ImportMetadataForm
        defaultName={preview.source_filename ?? entry.fileName}
        detectedCrs={raster ? preview.crs_epsg : fp?.crs ?? null}
        onCommit={(req) => {
          const layerName = getLayerName();
          onCommitSingle(entry.id, layerName ? { ...req, layer_name: layerName } : req);
        }}
        isCommitting={isCommitting}
        isRaster={raster}
        previewData={raster ? preview : undefined}
        previewColumns={fp?.columns}
        detectedGeometryType={fp?.geometry_type}
        detectedGeometryColumns={fp?.detected_geometry_columns}
      />
    </div>
  );
}

/* ── Main list ───────────────────────────────────────── */

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
  const [expandedId, setExpandedId] = useState<string | null>(entries[0]?.id ?? null);

  const { readyCount, rasterReadyCount, vectorCount, rasterCount, tableCount } = useMemo(() => {
    let ready = 0, rasterReady = 0, vec = 0, ras = 0, tab = 0;
    for (const e of entries) {
      if (e.status === 'preview') {
        ready++;
        if (e.previewData && isRasterPreview(e.previewData)) rasterReady++;
      }
      if (!e.previewData) continue;
      if (isRasterPreview(e.previewData)) { ras++; }
      else if ((e.previewData as FilePreviewResponse).geometry_type) { vec++; }
      else { tab++; }
    }
    return { readyCount: ready, rasterReadyCount: rasterReady, vectorCount: vec, rasterCount: ras, tableCount: tab };
  }, [entries]);

  return (
    <div className="space-y-4">
      {/* File list card */}
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border bg-surface-0 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          <span>
            {t('review.headerStatus', { defaultValue: 'Detection complete' })} · <span className="text-success">{t('review.readyCount', { count: readyCount, defaultValue: `${readyCount} ready` })}</span>
          </span>
          <span className="flex-1" />
          <span>{t('review.headerHint', { defaultValue: 'Review each before committing' })}</span>
        </div>

        {/* File rows */}
        {entries.map((entry) => {
          const ext = fileExt(entry.fileName);
          const kind = kindFromEntry(entry);
          const isExpanded = expandedId === entry.id;
          const canExpand = entry.status === 'preview' || entry.status === 'committing' || entry.status === 'commit-failed';

          return (
            <div
              key={entry.id}
              className={cn(
                'border-b border-border last:border-0',
                isExpanded && canExpand && 'bg-primary/[0.03]',
              )}
            >
              <div
                role={canExpand ? 'button' : undefined}
                tabIndex={canExpand ? 0 : undefined}
                className={cn(
                  'grid grid-cols-[32px_1fr_auto] items-center gap-3 px-4 py-3',
                  canExpand && 'cursor-pointer',
                  isExpanded && canExpand && 'border-l-2 border-l-primary',
                )}
                onClick={() => canExpand && setExpandedId(isExpanded ? null : entry.id)}
                onKeyDown={(e) => {
                  if (canExpand && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    setExpandedId(isExpanded ? null : entry.id);
                  }
                }}
              >
                <TypeTag kind={kind} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {canExpand && (
                      isExpanded
                        ? <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
                        : <ChevronRight className="size-3.5 text-muted-foreground shrink-0 rtl-mirror" />
                    )}
                    <span className="truncate text-[13.5px] font-medium tracking-tight">
                      {entry.fileName.replace(/\.[^.]+$/, '')}
                      <span className="font-mono font-normal text-muted-foreground">{ext}</span>
                    </span>
                    {entry.status === 'tracking' && (
                      <Badge variant="outline" className="bg-success/10 text-success border-success/30 text-[10px]">
                        {t('bulk.committed')}
                      </Badge>
                    )}
                  </div>
                  {entry.previewData && (
                    <p className="mt-0.5 font-mono text-[11.5px] text-muted-foreground">
                      {isRasterPreview(entry.previewData)
                        ? `${entry.previewData.band_count} band · ${entry.previewData.width}×${entry.previewData.height} · ${entry.previewData.crs_epsg ? `EPSG:${entry.previewData.crs_epsg}` : '?'}`
                        : `${(entry.previewData as FilePreviewResponse).geometry_type ?? 'Table'} · ${(entry.previewData as FilePreviewResponse).feature_count != null ? formatNumber((entry.previewData as FilePreviewResponse).feature_count!) + ' features' : '—'} · ${(entry.previewData as FilePreviewResponse).crs ? `EPSG:${(entry.previewData as FilePreviewResponse).crs}` : 'no CRS'}`}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={entry.status} />
                  <button
                    onClick={(e) => { e.stopPropagation(); onRemove(entry.id); }}
                    disabled={entry.status === 'committing' || entry.status === 'tracking'}
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
                    aria-label={t('bulk.removeFile')}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              </div>

              {/* Expanded content */}
              {isExpanded && canExpand && entry.previewData && (
                <div className="px-4 pb-4">
                  {/* Sheet selector for multi-layer files */}
                  {isFilePreview(entry.previewData) &&
                    entry.previewData.layers &&
                    entry.previewData.layers.length > 1 && (
                      <div className="mb-3 space-y-1">
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

                  <DetectionPanel entry={entry} />

                  {(entry.status === 'preview' || entry.status === 'committing' || entry.status === 'commit-failed') && (
                    <ReviewFormBlock
                      entry={entry}
                      isCommitting={entry.status === 'committing'}
                      onCommitSingle={onCommitSingle}
                    />
                  )}

                  {entry.status === 'commit-failed' && entry.error && (
                    <p className="mt-2 text-sm text-destructive">{entry.error}</p>
                  )}
                </div>
              )}

              {/* Non-expanded error */}
              {!isExpanded && entry.status === 'upload-failed' && entry.error && (
                <p className="px-4 pb-3 text-sm text-destructive">{entry.error}</p>
              )}
            </div>
          );
        })}
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-3 border-t border-dashed border-border pt-4">
        <div className="flex-1">
          <p className="text-[13px] font-semibold">
            {entries.length} files · {vectorCount} vector · {rasterCount} raster · {tableCount} tabular
          </p>
          <p className="font-mono text-[11px] text-muted-foreground tracking-wide">
            {t('review.actionHint', { defaultValue: 'Default import: each file → new dataset in the Catalog.' })}
          </p>
        </div>
        <div className="flex gap-2">
          {rasterReadyCount >= 2 && onCommitAllAsVrt && (
            <Button
              variant="secondary"
              onClick={onCommitAllAsVrt}
              disabled={readyCount === 0 || isCommitting}
            >
              <Layers className="me-1 size-3" />
              {t('bulk.importAsVrt', { defaultValue: 'Import as VRT Mosaic' })}
            </Button>
          )}
          <Button
            onClick={onCommitAll}
            disabled={readyCount === 0 || isCommitting}
          >
            {t('bulk.importAllDefaults', { defaultValue: `Import ${readyCount} files` })}
          </Button>
        </div>
      </div>
    </div>
  );
}
