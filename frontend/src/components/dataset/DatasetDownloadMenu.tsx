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
import { exportFormatsFor, exportFilename, type ExportFormat } from '@/lib/export-formats';

interface DatasetDownloadMenuProps {
  datasetId: string;
  datasetName: string;
  /** Null for a dataset without a geometry column, which exports CSV only. */
  geometryType?: string | null;
}

export function DatasetDownloadMenu({ datasetId, datasetName, geometryType }: DatasetDownloadMenuProps) {
  const { t } = useTranslation('dataset');

  const handleSelect = async (format: ExportFormat) => {
    try {
      await downloadExport(datasetId, format, exportFilename(datasetName, format));
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
        {exportFormatsFor(geometryType).map((f) => (
          <DropdownMenuItem
            key={f.value}
            onSelect={() => void handleSelect(f.value)}
          >
            {t(f.labelKey)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
