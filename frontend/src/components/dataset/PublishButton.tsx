import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe, GlobeLock, AlertCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useUpdatePublicationStatus, useValidation } from '@/hooks/use-dataset';
import { useAllSettings } from '@/hooks/use-settings';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
} from '@/components/ui/popover';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface PublishButtonProps {
  datasetId: string;
  currentStatus: string | null;
  className?: string;
}

export function PublishButton({ datasetId, currentStatus, className }: PublishButtonProps) {
  const { t } = useTranslation('dataset');
  const updateStatus = useUpdatePublicationStatus();
  const { data: validation } = useValidation(datasetId);
  const { data: allSettings } = useAllSettings();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isPublished = currentStatus === 'published';
  const hasErrors = validation ? validation.errors.length > 0 : false;
  const requireMetadata = allSettings?.tabs?.general?.find((s: { key: string }) => s.key === 'require_metadata_for_publish')?.value ?? false;
  const isMutating = updateStatus.isPending;

  const handleUnpublish = async () => {
    try {
      // Transition through: published -> internal -> ready -> draft
      const steps = ['internal', 'ready', 'draft'];
      for (const step of steps) {
        await updateStatus.mutateAsync({ datasetId, status: step });
      }
      toast.success(t('publish.unpublished'));
    } catch {
      toast.error(t('publish.failed'));
    } finally {
      setConfirmOpen(false);
    }
  };

  const handleClick = async () => {
    if (isPublished) {
      setConfirmOpen(true);
      return;
    }

    // Draft -> Publish: check validation first (only when metadata is required)
    if (requireMetadata && hasErrors) {
      setPopoverOpen(true);
      return;
    }

    try {
      // Transition through: draft -> ready -> internal -> published
      const steps = ['ready', 'internal', 'published'];
      for (const step of steps) {
        await updateStatus.mutateAsync({ datasetId, status: step });
      }
      toast.success(t('publish.success'));
    } catch {
      toast.error(t('publish.failed'));
    }
  };

  return (
    <>
      <div className="relative inline-flex">
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <PopoverTrigger asChild>
            <span className="sr-only" aria-hidden />
          </PopoverTrigger>
          <Button
            variant={isPublished ? 'outline' : 'default'}
            size="sm"
            onClick={handleClick}
            disabled={isMutating}
            className={className}
            data-testid="publish-button"
          >
            {isMutating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isPublished ? (
              <GlobeLock className="h-4 w-4" />
            ) : (
              <Globe className="h-4 w-4" />
            )}
            {isPublished ? t('publish.unpublish') : t('publish.publish')}
          </Button>
          <PopoverContent align="end" className="w-80">
            <PopoverHeader>
              <PopoverTitle className="flex items-center gap-1.5 text-destructive">
                <AlertCircle className="h-4 w-4" />
                {t('publish.validationBlocker')}
              </PopoverTitle>
            </PopoverHeader>
            {validation && validation.errors.length > 0 && (
              <ul className="mt-2 space-y-1">
                {validation.errors.map((issue, i) => (
                  <li key={i} className="text-sm text-muted-foreground">
                    <span className="font-medium">{issue.field}:</span> {issue.message}
                  </li>
                ))}
              </ul>
            )}
            <Button
              type="button"
              variant="link"
              size="sm"
              className="mt-2 h-auto px-0"
              onClick={() => {
                setPopoverOpen(false);
                // Navigate to overview tab for troubleshooting
                window.location.hash = 'overview';
              }}
            >
              {t('validation.troubleshootAction', { defaultValue: 'Troubleshoot' })}
            </Button>
          </PopoverContent>
        </Popover>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('publish.unpublishTitle', { defaultValue: 'Unpublish Dataset?' })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('publish.confirmUnpublish')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={handleUnpublish}>
              {t('publish.unpublish')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
