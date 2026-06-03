import { useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { VrtCreatorForm } from '@/components/import/VrtCreatorForm';

interface VrtCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSourceId?: string;
  initialSourceIds?: string[];
}

export function VrtCreateDialog({ open, onOpenChange, initialSourceId, initialSourceIds }: VrtCreateDialogProps) {
  const { t } = useTranslation('import');
  const openCountRef = useRef(0);

  // Increment key each time dialog opens to remount VrtCreatorForm with clean state
  useEffect(() => {
    if (open) {
      openCountRef.current += 1;
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('vrt.pageTitle')}</DialogTitle>
          <DialogDescription>{t('vrt.dialogDescription')}</DialogDescription>
        </DialogHeader>
        <VrtCreatorForm
          key={openCountRef.current}
          initialSourceId={initialSourceId}
          initialSourceIds={initialSourceIds}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
