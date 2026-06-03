import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { downloadExport } from '@/api/datasets';
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
        <label htmlFor={selectId} className="sr-only">
          {t('export.formatLabel', { defaultValue: 'Export format' })}
        </label>
        <select
          id={selectId}
          value={effectiveFormat}
          onChange={(e) => setFormat(e.target.value)}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
          disabled={loading}
        >
          {formats.map((f) => (
            <option key={f.value} value={f.value}>
              {t(f.labelKey)}
            </option>
          ))}
        </select>
        <Button onClick={handleExport} disabled={loading} className="shrink-0">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin me-2" />
          ) : (
            <Download className="h-4 w-4 me-2" />
          )}
          {t('export.button')}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
