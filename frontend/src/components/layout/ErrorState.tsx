import type { ReactNode } from 'react';
import { AlertCircle, RotateCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

interface ErrorStateProps {
  message: string;
  title?: string;
  /**
   * fix(#438): UX-02 — pass a query's `refetch` here and ErrorState renders a
   * standard "Try again" button. Previously the only recovery from a failed
   * list/detail query was a full-page reload. `action` still exists for the
   * rare non-retry recovery (e.g. a "Go back" link).
   */
  onRetry?: () => void;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({ message, title, onRetry, action, className }: ErrorStateProps) {
  const { t } = useTranslation('common');

  return (
    <div role="alert" aria-live="assertive" className={cn('rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center', className)}>
      <AlertCircle className="mx-auto size-8 text-destructive mb-3" />
      {title && <h2 className="text-lg font-semibold mb-1">{title}</h2>}
      <p className="text-sm text-destructive">{message}</p>
      {(onRetry || action) && (
        <div className="mt-4 flex items-center justify-center gap-2">
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RotateCw className="me-2 size-4" />
              {t('actions.retry')}
            </Button>
          )}
          {action}
        </div>
      )}
    </div>
  );
}
