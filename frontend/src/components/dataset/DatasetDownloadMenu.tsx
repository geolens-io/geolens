import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { downloadExport } from '@/api/datasets';
import type { RecordType } from '@/types/api';

const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
  { value: 'parquet', labelKey: 'export.parquet', ext: 'parquet' },
  { value: 'fgb', labelKey: 'export.fgb', ext: 'fgb' },
  { value: 'pmtiles', labelKey: 'export.pmtiles', ext: 'pmtiles' },
] as const;

const CSV_ONLY = EXPORT_FORMATS.filter((f) => f.value === 'csv');

function exportFormatsFor(recordType?: RecordType) {
  return recordType === 'table' ? CSV_ONLY : EXPORT_FORMATS;
}

interface DatasetDownloadMenuProps {
  datasetId: string;
  datasetName: string;
  recordType?: RecordType;
}

export function DatasetDownloadMenu({ datasetId, datasetName, recordType }: DatasetDownloadMenuProps) {
  const { t } = useTranslation('dataset');

  const handleSelect = async (format: string, ext: string) => {
    try {
      await downloadExport(datasetId, format, `${datasetName}.${ext}`);
    } catch {
      toast.error(t('export.failed'));
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" data-testid="dataset-header-download">
          <Download className="h-4 w-4" />
          {t('actions.download', { defaultValue: 'Download' })}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {exportFormatsFor(recordType).map((f) => (
          <DropdownMenuItem
            key={f.value}
            onSelect={() => void handleSelect(f.value, f.ext)}
            data-testid={`dataset-header-download-${f.value}`}
          >
            {t(f.labelKey)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
