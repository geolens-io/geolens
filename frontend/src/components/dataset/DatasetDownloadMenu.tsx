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
import { exportFormatsFor, exportFilename } from '@/lib/export-formats';
import type { RecordType } from '@/types/api';

interface DatasetDownloadMenuProps {
  datasetId: string;
  datasetName: string;
  recordType?: RecordType;
}

export function DatasetDownloadMenu({ datasetId, datasetName, recordType }: DatasetDownloadMenuProps) {
  const { t } = useTranslation('dataset');

  const handleSelect = async (format: string) => {
    try {
      await downloadExport(datasetId, format, exportFilename(datasetName, format) ?? `${datasetName}.${format}`);
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
            onSelect={() => void handleSelect(f.value)}
            data-testid={`dataset-header-download-${f.value}`}
          >
            {t(f.labelKey)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
