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
import { triggerDownload, datedFilename } from '@/lib/download';

interface ExportSplitButtonProps {
  filters: {
    user_id?: string;
    action?: string;
    resource_type?: string;
    resource_id?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
  };
  disabled?: boolean;
}

export function ExportSplitButton({ filters, disabled = false }: ExportSplitButtonProps) {
  const { t } = useTranslation('admin');
  const [isExporting, setIsExporting] = useState(false);

  async function handleExport(format: 'csv' | 'json') {
    setIsExporting(true);
    try {
      const blob = await exportAuditLogs(format, filters);
      triggerDownload(blob, datedFilename('audit-export', format));
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
        disabled={disabled || isExporting}
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
            variant="default"
            size="sm"
            className="rounded-s-none border-s border-primary-foreground/30 px-1.5"
            disabled={disabled || isExporting}
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
