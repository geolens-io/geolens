import { useTranslation } from 'react-i18next';
import { LifeBuoy } from 'lucide-react';
import { countDistinctFailures, useReportDialog, useReportEntries } from '@/lib/report';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ReportProblemWizard } from './ReportProblemWizard';

/**
 * App-wide host for the in-app problem reporter. Owns the report wizard, which
 * is opened from two entry points:
 *   - the user-menu "Report a problem" item (always available — see Navbar), and
 *   - a floating button that appears ONLY once errors are captured, surfacing a
 *     count badge so a user notices a problem the moment it happens.
 *
 * Available to everyone, signed in or not. Capture runs app-wide via
 * initReportCapture() (main.tsx); this only owns the affordance + wizard.
 * Anonymous visitors matter here: on a public instance most traffic browses
 * without an account, the floating button only appears once an error is
 * captured, and the wizard's output is a prefilled GitHub issue — nothing
 * about it needs a GeoLens session. (Originally auth-gated; relaxed so an
 * anonymous visitor who hits a broken map can still tell someone.)
 */
export function ReportProblemHost() {
  const entries = useReportEntries();
  const { t } = useTranslation('report');
  const open = useReportDialog((s) => s.open);
  const setOpen = useReportDialog((s) => s.setOpen);

  // fix(#908): distinct failures, not rows — one unrecovered map error writes
  // both a `maplibre` row and a `console` row, and the badge used to read "2".
  const errorCount = countDistinctFailures(entries);
  const hasErrors = errorCount > 0;
  const badge = errorCount > 9 ? '9+' : String(errorCount);

  return (
    <>
      {/* Floating button: only present when something is captured, so the idle
          UI footprint is zero and a real problem still surfaces proactively. */}
      {hasErrors && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={t('button.ariaWithCount', { count: errorCount })}
              onClick={() => setOpen(true)}
              className={cn(
                // bottom-10 (not bottom-4) clears the MapLibre attribution bar
                // that hugs the bottom-right corner of every map view.
                'fixed bottom-10 right-4 z-40 inline-flex size-10 items-center justify-center rounded-full border border-destructive/50 bg-background/90 text-destructive shadow-sm backdrop-blur transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              )}
            >
              <LifeBuoy className="size-5" aria-hidden />
              <span
                aria-live="polite"
                aria-atomic="true"
                className="absolute -right-1 -top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-2xs font-semibold leading-none text-destructive-foreground"
              >
                {badge}
              </span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="left">{t('button.tooltip')}</TooltipContent>
        </Tooltip>
      )}
      <ReportProblemWizard open={open} onOpenChange={setOpen} entries={entries} />
    </>
  );
}
