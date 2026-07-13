import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { downloadExport } from '@/api/datasets';
import { CopyButton } from '@/components/ui/copy-button';
import { Download, Loader2 } from 'lucide-react';
import type { RecordType } from '@/types/api';

interface ExportButtonProps {
  datasetId: string;
  datasetName: string;
  recordType?: RecordType;
}

const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
  { value: 'parquet', labelKey: 'export.parquet', ext: 'parquet' },
] as const;

const CSV_ONLY = EXPORT_FORMATS.filter((f) => f.value === 'csv');

export function ExportButton({ datasetId, datasetName, recordType }: ExportButtonProps) {
  const { t } = useTranslation('dataset');
  const formats = recordType === 'table' ? CSV_ONLY : EXPORT_FORMATS;
  const [format, setFormat] = useState<string>(formats[0]?.value ?? 'gpkg');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectId = `export-format-${datasetId}`;

  // Derive effective format — if current selection isn't in the available list, reset
  const effectiveFormat = formats.some((f) => f.value === format) ? format : formats[0]?.value ?? 'gpkg';

  // GeoParquet is a lakehouse-native format — show a copy-paste DuckDB snippet
  // so the download becomes queryable, not just archived. Points at the local
  // file (works for any dataset, no auth caveats). Match the browser-saved
  // filename so the snippet actually resolves: browsers replace path separators
  // (/ \) in anchor.download, so mirror that here, then double single quotes so
  // a title like "Bob's Roads" stays a valid DuckDB string literal.
  const duckdbFile = `${datasetName.replace(/[/\\]/g, '_').replace(/'/g, "''")}.parquet`;
  const duckdbSnippet = `INSTALL spatial; LOAD spatial;\nSELECT * FROM '${duckdbFile}' LIMIT 10;`;

  const handleExport = async () => {
    setLoading(true);
    setError(null);
    try {
      const selected = EXPORT_FORMATS.find((f) => f.value === effectiveFormat);
      const filename = `${datasetName}.${selected?.ext ?? effectiveFormat}`;
      await downloadExport(datasetId, effectiveFormat, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('export.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {/* fix(#438): DS-08 — was a native <select>; ui/select restores the
            themed, coarse-pointer-friendly dropdown. */}
        <Select value={effectiveFormat} onValueChange={setFormat} disabled={loading}>
          <SelectTrigger
            id={selectId}
            className="w-full"
            aria-label={t('export.formatLabel', { defaultValue: 'Export format' })}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {formats.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {t(f.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={handleExport} disabled={loading} className="shrink-0">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin me-2" />
          ) : (
            <Download className="h-4 w-4 me-2" />
          )}
          {t('export.button')}
        </Button>
      </div>
      {effectiveFormat === 'parquet' && (
        <div className="rounded-md border bg-muted/30 p-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="font-mono text-2xs uppercase tracking-wide text-muted-foreground">
              {t('export.duckdbHint', { defaultValue: 'Query with DuckDB' })}
            </span>
            <CopyButton value={duckdbSnippet} />
          </div>
          <pre className="overflow-x-auto text-2xs leading-5 text-foreground">
            <code>{duckdbSnippet}</code>
          </pre>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
