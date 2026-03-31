import type { ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ErrorStateProps {
  message: string;
  title?: string;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({ message, title, action, className }: ErrorStateProps) {
  return (
    <div role="alert" aria-live="assertive" className={cn('rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center', className)}>
      <AlertCircle className="mx-auto size-8 text-destructive mb-3" />
      {title && <h2 className="text-lg font-semibold mb-1">{title}</h2>}
      <p className="text-sm text-destructive">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
