import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageShellProps {
  maxWidth?: 'default' | 'wide' | 'narrow';
  className?: string;
  children: ReactNode;
}

export function PageShell({ maxWidth = 'default', className, children }: PageShellProps) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-6 py-4 space-y-4',
        maxWidth === 'narrow' ? 'max-w-4xl' : maxWidth === 'wide' ? 'max-w-6xl' : 'max-w-7xl',
        className,
      )}
    >
      {children}
    </div>
  );
}
