import { useRef, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import type { CommitImportRequest, RasterPreviewResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { stripExtension } from './utils';

type GeometryMode = 'auto' | 'manual' | 'none';
type GeometryType = 'latlng' | 'wkt';

interface ImportMetadataFormProps {
  defaultName: string;
  detectedCrs: number | null;
  onCommit: (metadata: CommitImportRequest) => void;
  isCommitting: boolean;
  isRaster?: boolean;
  previewData?: RasterPreviewResponse;
  previewColumns?: { name: string; type: string }[];
  detectedGeometryType?: string | null;
  detectedGeometryColumns?: {
    x_column: string | null;
    y_column: string | null;
    wkt_column: string | null;
  } | null;
}

const VISIBILITY_OPTIONS = [
  { value: 'private', labelKey: 'metadata.visibilityPrivate' },
  { value: 'restricted', labelKey: 'metadata.visibilityRestricted' },
  { value: 'public', labelKey: 'metadata.visibilityPublic' },
];

const COMPRESSION_OPTIONS = ['DEFLATE', 'ZSTD', 'LZW', 'JPEG', 'WEBP', 'LERC'];
const RESAMPLING_OPTIONS = [
  'auto',
  'nearest',
  'bilinear',
  'cubic',
  'cubicspline',
  'lanczos',
  'average',
  'mode',
];

export function ImportMetadataForm({
  defaultName,
  detectedCrs,
  onCommit,
  isCommitting,
  isRaster = false,
  previewData,
  previewColumns,
  detectedGeometryType,
  detectedGeometryColumns,
}: ImportMetadataFormProps) {
  const { t } = useTranslation('import');
  const [name, setName] = useState(stripExtension(defaultName));
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState('private');
  const [sridOverride, setSridOverride] = useState('');

  // Geometry column override state
  const hasDetected =
    detectedGeometryColumns &&
    (detectedGeometryColumns.x_column || detectedGeometryColumns.wkt_column);
  const [geomMode, setGeomMode] = useState<GeometryMode>(
    hasDetected ? 'auto' : 'none',
  );
  const [geomType, setGeomType] = useState<GeometryType>(
    detectedGeometryColumns?.wkt_column && !detectedGeometryColumns?.x_column
      ? 'wkt'
      : 'latlng',
  );
  const [xColumn, setXColumn] = useState(
    detectedGeometryColumns?.x_column ?? '',
  );
  const [yColumn, setYColumn] = useState(
    detectedGeometryColumns?.y_column ?? '',
  );
  const [wktColumn, setWktColumn] = useState(
    detectedGeometryColumns?.wkt_column ?? '',
  );

  // Columns eligible for Lat/Lng selection: numeric types preferred,
  // but include auto-detected columns even if GDAL typed them as String
  // (common with CSV where AUTODETECT_TYPE may not be applied).
  const numericColumns = useMemo(() => {
    const numeric = (previewColumns ?? []).filter((c) =>
      ['Real', 'Integer', 'Integer64'].includes(c.type),
    );
    if (numeric.length > 0) return numeric;
    // Fallback: if no numeric columns exist but auto-detected columns were
    // identified, show all columns so the user can select them manually.
    if (detectedGeometryColumns?.x_column || detectedGeometryColumns?.y_column) {
      return previewColumns ?? [];
    }
    return numeric;
  }, [previewColumns, detectedGeometryColumns]);
  const stringColumns = (previewColumns ?? []).filter(
    (c) => c.type === 'String',
  );
  const hasEmbeddedGeometry = Boolean(detectedGeometryType);
  const showEmbeddedGeometrySection = !isRaster && hasEmbeddedGeometry;
  const showGeomSection =
    !isRaster && !hasEmbeddedGeometry && previewColumns && previewColumns.length > 0;

  // Raster-specific fields
  const [temporalStart, setTemporalStart] = useState(
    previewData?.temporal_start ?? '',
  );
  const [temporalEnd, setTemporalEnd] = useState('');
  const [compression, setCompression] = useState('DEFLATE');
  const [resampling, setResampling] = useState('auto');
  const [nodataOverride, setNodataOverride] = useState('');

  const submittingRef = useRef(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    // Reset after the commit callback completes (or fails)
    queueMicrotask(() => { submittingRef.current = false; });

    const request: CommitImportRequest = {
      title: name.trim(),
      summary: description.trim() || null,
      visibility,
      srid_override: sridOverride.trim()
        ? parseInt(sridOverride.trim(), 10)
        : null,
    };

    // Add geometry column overrides
    if (showGeomSection && geomMode !== 'none') {
      if (geomType === 'latlng' && xColumn && yColumn) {
        request.x_column = xColumn;
        request.y_column = yColumn;
      } else if (geomType === 'wkt' && wktColumn) {
        request.geom_column = wktColumn;
      }
    }

    if (isRaster) {
      request.temporal_start = temporalStart || null;
      request.temporal_end = temporalEnd || null;
      request.compression = compression !== 'DEFLATE' ? compression : null;
      request.resampling = resampling !== 'auto' ? resampling : null;
      request.nodata_override = nodataOverride.trim()
        ? nodataOverride.trim()
        : null;
    }

    onCommit(request);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('metadata.title')}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="import-name">{t('metadata.nameLabel')}</Label>
            <Input
              id="import-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="import-description">{t('metadata.descriptionLabel')}</Label>
            <Input
              id="import-description"
              placeholder={t('metadata.descriptionPlaceholder')}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="import-visibility">{t('metadata.visibilityLabel')}</Label>
            <select
              id="import-visibility"
              value={visibility}
              onChange={(e) => setVisibility(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
            >
              {VISIBILITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {t(opt.labelKey)}
                </option>
              ))}
            </select>
          </div>

          {/* CRS Override — Phase 1057 CRS-06 D-08:
              When detectedCrs is non-null (probe resolved the CRS automatically),
              hide the editable override input and show a read-only confirmation
              instead.  When detectedCrs is null (unrecognised URI, true-unknown,
              or probe-CRS-not-available), the manual input stays visible as an
              escape hatch so the user can still supply an EPSG override. */}
          {detectedCrs ? (
            <div className="space-y-2">
              <Label>{t('metadata.crsLabel')}</Label>
              <p className="text-sm text-muted-foreground">
                {t('metadata.crsDetected', {
                  crs: detectedCrs,
                  defaultValue: `Detected CRS: EPSG:${detectedCrs} (auto-detected — no override needed)`,
                })}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="import-crs">{t('metadata.crsLabel')}</Label>
              <Input
                id="import-crs"
                type="number"
                placeholder={t('metadata.crsPlaceholderEmpty')}
                value={sridOverride}
                onChange={(e) => setSridOverride(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t('metadata.crsHelpText')}
              </p>
            </div>
          )}

          {showEmbeddedGeometrySection && (
            <div className="space-y-3 rounded-md border border-success/30 bg-success/5 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">
                  {t('metadata.geometryColumns')}
                </p>
                <Badge variant="outline" className="border-success/40 bg-background/80">
                  {detectedGeometryType
                    ? getGeometryTypeLabel(t, detectedGeometryType)
                    : t('preview.unknown')}
                </Badge>
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">
                  {t('metadata.embeddedGeometry', {
                    defaultValue: 'Using embedded geometry',
                  })}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t('metadata.embeddedGeometryHelp', {
                    defaultValue: 'This source already includes native geometry, so GeoLens will keep it during import.',
                  })}
                </p>
              </div>
            </div>
          )}

          {showGeomSection && (
            <div className="space-y-3 rounded-md border p-3">
              <p className="text-sm font-medium">
                {t('metadata.geometryColumns')}
              </p>

              <div className="space-y-1">
                <Label htmlFor="geom-mode">
                  {t('metadata.geometryMode')}
                </Label>
                <select
                  id="geom-mode"
                  value={geomMode}
                  onChange={(e) =>
                    setGeomMode(e.target.value as GeometryMode)
                  }
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                >
                  {hasDetected && (
                    <option value="auto">
                      {t('metadata.autoDetected')}
                    </option>
                  )}
                  <option value="manual">
                    {t('metadata.manualOverride')}
                  </option>
                  <option value="none">
                    {t('metadata.nonSpatial')}
                  </option>
                </select>
              </div>

              {geomMode !== 'none' && (
                <>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-1.5 text-sm">
                      <input
                        type="radio"
                        name="geom-type"
                        value="latlng"
                        checked={geomType === 'latlng'}
                        onChange={() => setGeomType('latlng')}
                      />
                      {t('metadata.latLng')}
                    </label>
                    <label className="flex items-center gap-1.5 text-sm">
                      <input
                        type="radio"
                        name="geom-type"
                        value="wkt"
                        checked={geomType === 'wkt'}
                        onChange={() => setGeomType('wkt')}
                      />
                      {t('metadata.wkt')}
                    </label>
                  </div>

                  {geomType === 'latlng' ? (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="x-column">
                          {t('metadata.xColumn')}
                        </Label>
                        <select
                          id="x-column"
                          value={xColumn}
                          onChange={(e) => setXColumn(e.target.value)}
                          disabled={geomMode === 'auto'}
                          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-60"
                        >
                          <option value="">--</option>
                          {numericColumns.map((c) => (
                            <option key={c.name} value={c.name}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="y-column">
                          {t('metadata.yColumn')}
                        </Label>
                        <select
                          id="y-column"
                          value={yColumn}
                          onChange={(e) => setYColumn(e.target.value)}
                          disabled={geomMode === 'auto'}
                          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-60"
                        >
                          <option value="">--</option>
                          {numericColumns.map((c) => (
                            <option key={c.name} value={c.name}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <Label htmlFor="wkt-column">
                        {t('metadata.wktColumn')}
                      </Label>
                      <select
                        id="wkt-column"
                        value={wktColumn}
                        onChange={(e) => setWktColumn(e.target.value)}
                        disabled={geomMode === 'auto'}
                        className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-60"
                      >
                        <option value="">--</option>
                        {stringColumns.map((c) => (
                          <option key={c.name} value={c.name}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {isRaster && (
            <>
              {/* Temporal dates */}
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="temporal-start">
                      {t('metadata.temporalStartLabel')}
                    </Label>
                    <Input
                      id="temporal-start"
                      type="date"
                      value={temporalStart}
                      onChange={(e) => setTemporalStart(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="temporal-end">
                      {t('metadata.temporalEndLabel')}
                    </Label>
                    <Input
                      id="temporal-end"
                      type="date"
                      value={temporalEnd}
                      onChange={(e) => setTemporalEnd(e.target.value)}
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('metadata.temporalHelpText')}
                </p>
              </div>

              {/* Advanced GDAL Options */}
              <div className="space-y-3 rounded-md border p-3">
                <p className="text-sm font-medium text-muted-foreground">
                  {t('metadata.advancedOptions')}
                </p>

                <div className="space-y-1">
                  <Label htmlFor="compression">
                    {t('metadata.compressionLabel')}
                  </Label>
                  <select
                    id="compression"
                    value={compression}
                    onChange={(e) => setCompression(e.target.value)}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                  >
                    {COMPRESSION_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    {t('metadata.compressionHelp')}
                  </p>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="resampling">
                    {t('metadata.resamplingLabel')}
                  </Label>
                  <select
                    id="resampling"
                    value={resampling}
                    onChange={(e) => setResampling(e.target.value)}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                  >
                    {RESAMPLING_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt === 'auto' ? `(${opt})` : opt}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    {t('metadata.resamplingHelp')}
                  </p>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="nodata-override">
                    {t('metadata.nodataLabel')}
                  </Label>
                  <Input
                    id="nodata-override"
                    type="text"
                    placeholder=""
                    value={nodataOverride}
                    onChange={(e) => setNodataOverride(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t('metadata.nodataHelp')}
                  </p>
                </div>
              </div>
            </>
          )}

          <Button type="submit" disabled={isCommitting || !name.trim()}>
            {isCommitting && <Loader2 className="size-4 animate-spin" />}
            {isCommitting ? t('metadata.importing') : t('metadata.importDataset')}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
