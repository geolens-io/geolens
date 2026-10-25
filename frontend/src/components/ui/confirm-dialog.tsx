import type { ComponentProps, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
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

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  /** Defaults to the shared Cancel label. */
  cancelLabel?: ReactNode;
  /** Body between the description and the footer. */
  children?: ReactNode;
  /** Rendered between Cancel and the confirm action. */
  footerExtra?: ReactNode;
  /** Omit when the action cannot proceed; Cancel is then the only way out. */
  confirm?: {
    label: string;
    onClick: () => void;
    variant?: ComponentProps<typeof AlertDialogAction>['variant'];
    /** Shows a spinner and disables the action. */
    pending?: boolean;
  };
}

/** Confirmation dialog for an action the user must approve before it runs. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cancelLabel,
  children,
  footerExtra,
  confirm,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {/* Bounded independently of the body: a short viewport (phone landscape,
          high zoom) can otherwise push Cancel past the screen while the modal
          blocks page scroll. */}
      <AlertDialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelLabel ?? t('common:cancel')}</AlertDialogCancel>
          {footerExtra}
          {confirm && (
            <AlertDialogAction
              variant={confirm.variant}
              onClick={confirm.onClick}
              disabled={confirm.pending}
            >
              {confirm.pending && (
                <Loader2 className="h-3.5 w-3.5 animate-spin me-1.5" aria-hidden="true" />
              )}
              {confirm.label}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
