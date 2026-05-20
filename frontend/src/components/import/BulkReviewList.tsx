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
          {raster ? t('detect.rasterInfo') : t('detect.geometry')}
        </h5>
        <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-1 text-xs">
          {raster ? (
            <>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.bands')}</dt>
              <dd className="font-mono text-[11.5px]">{preview.band_count}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.size')}</dt>
              <dd className="font-mono text-[11.5px]">{preview.width} x {preview.height} px</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.dataType')}</dt>
              <dd className="font-mono text-[11.5px]">{preview.dtype}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.crs')}</dt>
              <dd className="font-mono text-[11.5px]">{preview.crs_epsg ? `EPSG:${preview.crs_epsg}` : t('preview.unknown')}</dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.cog')}</dt>
              <dd className="font-mono text-[11.5px]">
                {preview.is_cog_compliant
                  ? <span className="text-success">{t('detect.validCog')}</span>
                  : <span className="text-warning-foreground">{t('detect.willConvert')}</span>}
              </dd>
            </>
          ) : file ? (
            <>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.type')}</dt>
              <dd className="font-mono text-[11.5px]">
                {file.geometry_type ? getGeometryTypeLabel(t, file.geometry_type) : t('detect.nonSpatial')}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.features')}</dt>
              <dd className="font-mono text-[11.5px]">
                {file.feature_count != null ? formatNumber(file.feature_count) : '—'}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.crs')}</dt>
              <dd className="font-mono text-[11.5px]">
                {file.crs ? `EPSG:${file.crs}` : '—'}
                {file.crs && file.crs !== 4326 && file.crs !== 3857 && (
                  <span className="ms-1 text-muted-foreground">→ {t('detect.willReproject')}</span>
                )}
              </dd>
              <dt className="font-mono text-[11px] text-muted-foreground">{t('detect.labels.layer')}</dt>
              <dd className="font-mono text-[11.5px]">{file.layer_name}</dd>
            </>
          ) : null}
        </dl>
      </div>

      {/* Schema columns */}
      {file && file.columns.length > 0 && (
        <div>
          <h5 className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
            {t('detect.schema')} · {t('detect.columnCount', { count: file.columns.length, value: formatNumber(file.columns.length) })}
          </h5>
          <div className="max-h-44 overflow-y-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface-0">
                  <th className="px-2 py-1.5 text-start font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{t('detect.table.column')}</th>
                  <th className="px-2 py-1.5 text-start font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{t('detect.table.type')}</th>
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
                      {t('preview.moreColumns', { count: file.columns.length - 12 })}
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
  // GPKG-03 Phase 1058: optional fan-out prop — single-layer-only consumers can omit
  onIngestAllLayers?: (entryId: string) => void;
  isCommitting: boolean;
}

export function BulkReviewList({
  entries,
  onCommitSingle,
  onCommitAll,
  onCommitAllAsVrt,
  onRemove,
  onSheetChange,
  onIngestAllLayers,
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

  function formatCrs(crs: number | null | undefined, fallback: string) {
    return crs ? `EPSG:${crs}` : fallback;
  }

  function formatPreviewSummary(preview: FileEntry['previewData']): string {
    if (!preview) return '';

    if (isRasterPreview(preview)) {
      const bands = t('review.bandCount', {
        count: preview.band_count,
        value: formatNumber(preview.band_count),
      });
      return t('review.rasterSummary', {
        bands,
        width: formatNumber(preview.width),
        height: formatNumber(preview.height),
        crs: formatCrs(preview.crs_epsg, t('preview.unknown')),
      });
    }

    const geometryType = preview.geometry_type
      ? getGeometryTypeLabel(t, preview.geometry_type)
      : t('bulk.kindTable');
    const features = preview.feature_count != null
      ? t('review.featureCount', {
          count: preview.feature_count,
          value: formatNumber(preview.feature_count),
        })
      : '—';

    return t('review.vectorSummary', {
      geometryType,
      features,
      crs: formatCrs(preview.crs, t('review.noCrs')),
    });
  }

  function formatLayerOption(layer: { name: string; feature_count: number; field_count: number }) {
    const rows = t('bulk.rowCount', {
      count: layer.feature_count,
      value: formatNumber(layer.feature_count),
    });
    const columns = t('bulk.columnCount', {
      count: layer.field_count,
      value: formatNumber(layer.field_count),
    });

    return t('bulk.sheetOption', { name: layer.name, rows, columns });
  }

  function formatReviewCount(
    key: 'fileCount' | 'vectorCount' | 'rasterCount' | 'tableCount',
    count: number,
  ) {
    return t(`review.${key}`, { count, value: formatNumber(count) });
  }

  return (
    <div className="space-y-4">
      {/* File list card */}
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border bg-surface-0 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          <span>
            {t('review.headerStatus')} · <span className="text-success">{t('review.readyCount', { count: readyCount, value: formatNumber(readyCount) })}</span>
          </span>
          <span className="flex-1" />
          <span>{t('review.headerHint')}</span>
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
                      {formatPreviewSummary(entry.previewData)}
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
                        <Label htmlFor={`sheet-${entry.id}`}>{t('bulk.sheetLabel')}</Label>
                        <select
                          id={`sheet-${entry.id}`}
                          value={entry.previewData.layer_name}
                          onChange={(e) => onSheetChange?.(entry.id, e.target.value)}
                          className="h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                        >
                          {entry.previewData.layers.map((layer) => (
                            <option key={layer.name} value={layer.name}>
                              {formatLayerOption(layer)}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                  {/* GPKG-03 Phase 1058: "Ingest all layers" button for multi-layer files */}
                  {isFilePreview(entry.previewData) &&
                    entry.previewData.layers &&
                    entry.previewData.layers.length > 1 &&
                    onIngestAllLayers && (
                      <div className="mb-3">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => onIngestAllLayers(entry.id)}
                          disabled={isCommitting || entry.status !== 'preview'}
                          data-testid={`ingest-all-layers-${entry.id}`}
                        >
                          <Layers className="me-1 size-3" />
                          {t('bulk.ingestAllLayers', { count: entry.previewData.layers.length })}
                        </Button>
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
            {t('review.actionSummary', {
              files: formatReviewCount('fileCount', entries.length),
              vectors: formatReviewCount('vectorCount', vectorCount),
              rasters: formatReviewCount('rasterCount', rasterCount),
              tables: formatReviewCount('tableCount', tableCount),
            })}
          </p>
          <p className="font-mono text-[11px] text-muted-foreground tracking-wide">
            {t('review.actionHint')}
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
              {t('bulk.importAsVrt')}
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
    </div>
  );
}
