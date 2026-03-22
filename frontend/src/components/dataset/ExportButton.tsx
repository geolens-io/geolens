import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { downloadExport } from '@/api/datasets';
import { Download, Loader2 } from 'lucide-react';

interface ExportButtonProps {
  datasetId: string;
  datasetName: string;
}

const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
] as const;

export function ExportButton({ datasetId, datasetName }: ExportButtonProps) {
  const { t } = useTranslation('dataset');
  const [format, setFormat] = useState<string>('gpkg');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectId = `export-format-${datasetId}`;

  const handleExport = async () => {
    setLoading(true);
    setError(null);
    try {
      const selected = EXPORT_FORMATS.find((f) => f.value === format);
      const filename = `${datasetName}.${selected?.ext ?? format}`;
      await downloadExport(datasetId, format, filename);
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
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
          disabled={loading}
        >
          {EXPORT_FORMATS.map((f) => (
            <option key={f.value} value={f.value}>
              {t(f.labelKey)}
            </option>
          ))}
        </select>
        <Button onClick={handleExport} disabled={loading} className="shrink-0">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
          {t('export.button')}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
