import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, ChevronDown, Copy, ShieldCheck, Trash2 } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { GitHubIcon } from '@/components/icons/GitHubIcon';
import { cn } from '@/lib/utils';
import type { ReportEntry } from '@/lib/report';
import {
  ISSUE_AREAS,
  buildClipboardReport,
  buildContext,
  buildIssueUrl,
  buildTechnicalClipboard,
  clearReportEntries,
  mapAreaFromPath,
} from '@/lib/report';
import { ReportEntryList } from './ReportEntryList';
import { Textarea } from '@/components/ui/textarea';

// `__APP_VERSION__` is replaced at build by Vite's `define`. The typeof guard
// keeps this safe in any environment where the define isn't applied.
const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0';
const STEP_PLACEHOLDER = '1. \n2. \n3. ';
const TOTAL_STEPS = 3;

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    // Fall through to the legacy execCommand path (e.g. non-secure context).
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
  } catch {
    // Best effort — nothing more we can do.
  }
  document.body.removeChild(textarea);
}

interface ReportProblemWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entries: ReportEntry[];
}

export function ReportProblemWizard({ open, onOpenChange, entries }: ReportProblemWizardProps) {
  const { t, i18n } = useTranslation('report');
  const [step, setStep] = useState(1);
  const [area, setArea] = useState<string>('Other');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [steps, setSteps] = useState('');
  const [expected, setExpected] = useState('');
  const [includeErrors, setIncludeErrors] = useState(true);
  const [includePage, setIncludePage] = useState(true);
  const [includeEnv, setIncludeEnv] = useState(true);
  const [includeVersion, setIncludeVersion] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const problemCount = useMemo(() => entries.filter((e) => e.severity !== 'info').length, [entries]);

  // Tracks whether the previous session ended in a send/copy. A draft that was
  // dismissed accidentally (Esc, outside click) survives the next open; only a
  // completed report starts the wizard clean again.
  const submittedRef = useRef(true);

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setDetailsOpen(false);
    if (!submittedRef.current) return; // preserve the unsent draft
    submittedRef.current = false;
    setArea(mapAreaFromPath(window.location.pathname));
    setTitle('');
    setDescription('');
    setSteps('');
    setExpected('');
    setIncludeErrors(true);
    setIncludePage(true);
    setIncludeEnv(true);
    setIncludeVersion(true);
  }, [open]);

  function assembleContext(): string {
    return buildContext({
      entries,
      includeErrors,
      includeEnv,
      includePage,
      pageUrl: window.location.href,
      userAgent: navigator.userAgent,
      screen: `${window.innerWidth}×${window.innerHeight}`,
      language: i18n.language,
    });
  }

  function handleOpenIssue() {
    submittedRef.current = true;
    const context = assembleContext();
    const version = includeVersion ? APP_VERSION : '';
    const { url, truncated } = buildIssueUrl({ title, description, steps, expected, area, version, context });
    if (truncated) {
      // Initiate the clipboard copy within the user gesture but do NOT await it
      // before window.open — an await boundary here drops the gesture context,
      // so a popup blocker can kill the GitHub issue tab (the primary action).
      // The write is kicked off in-gesture (while this tab still has focus),
      // then the tab opens synchronously.
      void copyToClipboard(
        buildClipboardReport({ title, description, steps, expected, area, version, context }),
      ).then(() => toast.message(t('step3.truncatedToast')));
    }
    window.open(url, '_blank', 'noopener,noreferrer');
    onOpenChange(false);
  }

  async function handleCopy() {
    submittedRef.current = true;
    const context = assembleContext();
    const version = includeVersion ? APP_VERSION : '';
    await copyToClipboard(buildClipboardReport({ title, description, steps, expected, area, version, context }));
    toast.success(t('step3.copied'));
  }

  // Step-1 shortcut: grab just the environment + captured signals without
  // filling in anything. Does not count as sending, so the draft survives.
  async function handleCopyTechnical() {
    const context = assembleContext();
    const version = includeVersion ? APP_VERSION : '';
    await copyToClipboard(buildTechnicalClipboard({ version, context }));
    toast.success(t('technicalCopied'));
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle>{t('title')}</SheetTitle>
          <SheetDescription>{t('description')}</SheetDescription>
          <p aria-live="polite" className="text-xs font-medium text-muted-foreground">
            {t('stepIndicator', { current: step, total: TOTAL_STEPS })}
          </p>
        </SheetHeader>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {step === 1 && (
            <>
              <h3 className="text-sm font-semibold">{t('step1.heading')}</h3>

              <div className="space-y-1.5">
                <Label htmlFor="rp-area">{t('step1.areaLabel')}</Label>
                <Select value={area} onValueChange={setArea}>
                  <SelectTrigger id="rp-area" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ISSUE_AREAS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rp-title">{t('step1.titleLabel')}</Label>
                <Input
                  id="rp-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t('step1.titlePlaceholder')}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rp-description">{t('step1.descriptionLabel')}</Label>
                <Textarea
                  id="rp-description"
                  className="min-h-20"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('step1.descriptionPlaceholder')}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rp-steps">{t('step1.stepsLabel')}</Label>
                <Textarea
                  id="rp-steps"
                  className="min-h-20"
                  value={steps}
                  onChange={(e) => setSteps(e.target.value)}
                  placeholder={STEP_PLACEHOLDER}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rp-expected">{t('step1.expectedLabel')}</Label>
                <Textarea
                  id="rp-expected"
                  className="min-h-20"
                  value={expected}
                  onChange={(e) => setExpected(e.target.value)}
                  placeholder={t('step1.expectedPlaceholder')}
                />
              </div>

              <div
                className={cn(
                  'flex items-start gap-2 rounded-md border px-3 py-2 text-xs',
                  problemCount > 0
                    ? 'border-warning/40 bg-warning/5 text-foreground'
                    : 'border-border bg-muted/40 text-muted-foreground',
                )}
              >
                {problemCount > 0 && <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />}
                <span>{problemCount > 0 ? t('noticed', { count: problemCount }) : t('noticedNone')}</span>
              </div>

              <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
                <div className="flex items-center justify-between gap-2">
                  <CollapsibleTrigger className="flex min-w-0 items-center gap-1 rounded-sm text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', detailsOpen && 'rotate-180')} aria-hidden />
                    {t('technicalDetails', { count: entries.length })}
                  </CollapsibleTrigger>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button type="button" variant="ghost" size="xs" onClick={handleCopyTechnical}>
                      <Copy aria-hidden />
                      {t('technicalCopy')}
                    </Button>
                    {entries.length > 0 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        onClick={() => clearReportEntries()}
                        aria-label={t('technicalClearAria')}
                        title={t('technicalClearAria')}
                      >
                        <Trash2 aria-hidden />
                        {t('technicalClear')}
                      </Button>
                    )}
                  </div>
                </div>
                <CollapsibleContent className="pt-2">
                  <ReportEntryList entries={entries} />
                </CollapsibleContent>
              </Collapsible>
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <h3 className="text-sm font-semibold">{t('step2.heading')}</h3>
                <p className="mt-1 text-xs text-muted-foreground">{t('step2.subtitle')}</p>
              </div>

              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="rp-inc-errors"
                    checked={includeErrors}
                    onCheckedChange={(v) => setIncludeErrors(v === true)}
                    disabled={entries.length === 0}
                  />
                  <Label htmlFor="rp-inc-errors" className="font-normal">
                    {t('step2.includeErrors', { count: entries.length })}
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox id="rp-inc-page" checked={includePage} onCheckedChange={(v) => setIncludePage(v === true)} />
                  <Label htmlFor="rp-inc-page" className="font-normal">
                    {t('step2.includePage')}
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox id="rp-inc-env" checked={includeEnv} onCheckedChange={(v) => setIncludeEnv(v === true)} />
                  <Label htmlFor="rp-inc-env" className="font-normal">
                    {t('step2.includeEnv')}
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="rp-inc-version"
                    checked={includeVersion}
                    onCheckedChange={(v) => setIncludeVersion(v === true)}
                  />
                  <Label htmlFor="rp-inc-version" className="font-normal">
                    {t('step2.includeVersion', { version: APP_VERSION })}
                  </Label>
                </div>
              </div>

              <div className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                <div className="space-y-1">
                  <p>{t('step2.privacyNote')}</p>
                  <Popover>
                    <PopoverTrigger className="font-medium text-foreground underline underline-offset-2 hover:text-primary">
                      {t('step2.privacyMore')}
                    </PopoverTrigger>
                    <PopoverContent side="top" className="w-72 text-xs">
                      {t('step2.privacyDetail')}
                    </PopoverContent>
                  </Popover>
                </div>
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div>
                <h3 className="text-sm font-semibold">{t('step3.heading')}</h3>
                <p className="mt-1 text-xs text-muted-foreground">{t('step3.subtitle')}</p>
              </div>

              <div className="space-y-2">
                <Button className="w-full" onClick={handleOpenIssue}>
                  <GitHubIcon className="size-4" />
                  {t('step3.openIssue')}
                </Button>
                <Button variant="outline" className="w-full" onClick={handleCopy}>
                  {t('step3.copyReport')}
                </Button>
              </div>
            </>
          )}
        </div>

        <SheetFooter className="flex-row items-center justify-between gap-2 border-t">
          <div>
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep((s) => s - 1)}>
                {t('nav.back')}
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t('nav.cancel')}
            </Button>
            {step < TOTAL_STEPS && (
              <Button size="sm" onClick={() => setStep((s) => s + 1)} disabled={step === 1 && !description.trim()}>
                {t('nav.next')}
              </Button>
            )}
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
