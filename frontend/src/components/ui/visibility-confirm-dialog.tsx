import type { ReactNode } from 'react';
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

interface VisibilityConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  cancelLabel: ReactNode;
  /** Body between the description and the footer. */
  children?: ReactNode;
  /** Rendered between Cancel and the confirm action. */
  footerExtra?: ReactNode;
  /** Omit when the change cannot proceed; Cancel is then the only way out. */
  confirm?: {
    label: ReactNode;
    onClick: () => void;
    disabled?: boolean;
    destructive?: boolean;
  };
}

/** Confirmation shown before a visibility change crosses the public boundary. */
export function VisibilityConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cancelLabel,
  children,
  footerExtra,
  confirm,
}: VisibilityConfirmDialogProps) {
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
          <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
          {footerExtra}
          {confirm && (
            <AlertDialogAction
              variant={confirm.destructive ? 'destructive' : undefined}
              onClick={confirm.onClick}
              disabled={confirm.disabled}
            >
              {confirm.label}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
