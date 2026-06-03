import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, ChevronDown, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { exportAuditLogs } from '@/api/admin';

interface ExportSplitButtonProps {
  filters: {
    action?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
  };
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildFilename(format: 'csv' | 'json'): string {
  const date = new Date().toISOString().slice(0, 10);
  return `audit-export-${date}.${format}`;
}

export function ExportSplitButton({ filters }: ExportSplitButtonProps) {
  const { t } = useTranslation('admin');
  const [isExporting, setIsExporting] = useState(false);

  async function handleExport(format: 'csv' | 'json') {
    setIsExporting(true);
    try {
      const blob = await exportAuditLogs(format, filters);
      triggerDownload(blob, buildFilename(format));
    } catch {
      toast.error(t('audit.export.errorTitle'), {
        description: t('audit.export.errorBody'),
      });
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="flex items-center">
      <Button
        variant="default"
        size="sm"
        className="rounded-e-none"
        disabled={isExporting}
        aria-busy={isExporting || undefined}
        onClick={() => handleExport('csv')}
      >
        {isExporting ? (
          <Loader2 className="me-1 h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="me-1 h-3.5 w-3.5" />
        )}
        {isExporting ? t('audit.export.loading') : t('audit.export.csv')}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="rounded-s-none border-s border-l-border px-1.5"
            disabled={isExporting}
            aria-label={t('audit.export.formatOptions')}
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => handleExport('json')}>
            {t('audit.export.json')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
