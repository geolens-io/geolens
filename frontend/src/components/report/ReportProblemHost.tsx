import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LifeBuoy } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { useReportEntries } from '@/lib/report';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ReportProblemWizard } from './ReportProblemWizard';

/**
 * App-wide entry point for the in-app problem reporter. Renders a quiet
 * bottom-right button that stays out of the way until something is captured,
 * then surfaces an error count. Gated to authenticated users — the public
 * login / shared-map views never show it.
 *
 * Capture itself runs app-wide via initReportCapture() (main.tsx); this only
 * owns the affordance and the wizard.
 */
export function ReportProblemHost() {
  const token = useAuthStore((s) => s.token);
  const entries = useReportEntries();
  const { t } = useTranslation('report');
  const [open, setOpen] = useState(false);

  if (!token) return null;

  const errorCount = entries.reduce((count, entry) => count + (entry.severity === 'error' ? 1 : 0), 0);
  const hasErrors = errorCount > 0;
  const badge = errorCount > 9 ? '9+' : String(errorCount);

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={hasErrors ? t('button.ariaWithCount', { count: errorCount }) : t('button.aria')}
            onClick={() => setOpen(true)}
            className={cn(
              // bottom-10 (not bottom-4) clears the MapLibre attribution bar that
              // hugs the bottom-right corner of every map view — attribution must
              // stay unobstructed, and its compact toggle sits exactly here.
              'fixed bottom-10 right-4 z-40 inline-flex size-10 items-center justify-center rounded-full border bg-background/90 text-muted-foreground shadow-sm backdrop-blur transition-all duration-200 hover:text-foreground hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              hasErrors ? 'border-destructive/50 text-destructive opacity-100' : 'opacity-60',
            )}
          >
            <LifeBuoy className="size-5" aria-hidden />
            {hasErrors && (
              <span
                aria-live="polite"
                aria-atomic="true"
                className="absolute -right-1 -top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-destructive-foreground"
              >
                {badge}
              </span>
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent side="left">{t('button.tooltip')}</TooltipContent>
      </Tooltip>
      <ReportProblemWizard open={open} onOpenChange={setOpen} entries={entries} />
    </>
  );
}
