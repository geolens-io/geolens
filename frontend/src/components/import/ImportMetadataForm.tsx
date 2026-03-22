import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import type { CommitImportRequest, RasterPreviewResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface ImportMetadataFormProps {
  defaultName: string;
  detectedCrs: number | null;
  onCommit: (metadata: CommitImportRequest) => void;
  isCommitting: boolean;
  isRaster?: boolean;
  previewData?: RasterPreviewResponse;
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

function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export function ImportMetadataForm({
  defaultName,
  detectedCrs,
  onCommit,
  isCommitting,
  isRaster = false,
  previewData,
}: ImportMetadataFormProps) {
  const { t } = useTranslation('import');
  const [name, setName] = useState(stripExtension(defaultName));
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState('private');
  const [sridOverride, setSridOverride] = useState('');

  // Raster-specific fields
  const [temporalStart, setTemporalStart] = useState(
    previewData?.temporal_start ?? '',
  );
  const [temporalEnd, setTemporalEnd] = useState('');
  const [compression, setCompression] = useState('DEFLATE');
  const [resampling, setResampling] = useState('auto');
  const [nodataOverride, setNodataOverride] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const request: CommitImportRequest = {
      title: name.trim(),
      summary: description.trim() || null,
      visibility,
      srid_override: sridOverride.trim()
        ? parseInt(sridOverride.trim(), 10)
        : null,
    };

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

          <div className="space-y-2">
            <Label htmlFor="import-crs">{t('metadata.crsLabel')}</Label>
            <Input
              id="import-crs"
              type="number"
              placeholder={
                detectedCrs
                  ? t('metadata.crsPlaceholderDetected', { crs: detectedCrs })
                  : t('metadata.crsPlaceholderEmpty')
              }
              value={sridOverride}
              onChange={(e) => setSridOverride(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              {t('metadata.crsHelpText')}
            </p>
          </div>

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
