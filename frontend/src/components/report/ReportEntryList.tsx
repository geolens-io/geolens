import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, AlertTriangle, ChevronRight, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ReportEntry, ReportSeverity } from '@/lib/report';

function SeverityIcon({ severity }: { severity: ReportSeverity }) {
  if (severity === 'error') return <AlertCircle className="size-3.5 shrink-0 text-destructive" aria-hidden />;
  if (severity === 'warning') return <AlertTriangle className="size-3.5 shrink-0 text-warning" aria-hidden />;
  return <Info className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />;
}

function formatRelative(ts: number, language: string): string {
  const seconds = Math.round((ts - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  try {
    const rtf = new Intl.RelativeTimeFormat(language, { numeric: 'auto' });
    if (abs < 60) return rtf.format(seconds, 'second');
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute');
    return rtf.format(Math.round(seconds / 3600), 'hour');
  } catch {
    return '';
  }
}

function EntryRow({ entry, language }: { entry: ReportEntry; language: string }) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = Boolean(entry.detail);

  return (
    <li className="border-b border-border/60 last:border-0">
      <button
        type="button"
        onClick={() => canExpand && setExpanded((v) => !v)}
        className={cn(
          'flex w-full items-start gap-2 px-2 py-1.5 text-left text-xs',
          canExpand ? 'cursor-pointer hover:bg-muted/50' : 'cursor-default',
        )}
        aria-expanded={canExpand ? expanded : undefined}
      >
        <SeverityIcon severity={entry.severity} />
        <span className="shrink-0 rounded bg-muted px-1 py-0.5 font-mono text-[10px] uppercase text-muted-foreground">
          {entry.source}
        </span>
        <span className="min-w-0 flex-1 break-words font-mono text-foreground/90">
          {entry.message}
          {entry.count > 1 && <span className="ml-1 text-muted-foreground">×{entry.count}</span>}
          {entry.suppressed && <span className="ml-1 italic text-muted-foreground">(suppressed)</span>}
        </span>
        <span className="shrink-0 text-[10px] text-muted-foreground">{formatRelative(entry.ts, language)}</span>
        {canExpand && (
          <ChevronRight
            className={cn('size-3 shrink-0 text-muted-foreground transition-transform', expanded && 'rotate-90')}
            aria-hidden
          />
        )}
      </button>
      {expanded && entry.detail && (
        <pre className="mb-1.5 ml-7 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/70 p-2 text-[10px] leading-relaxed text-muted-foreground">
          {entry.detail}
        </pre>
      )}
    </li>
  );
}

/** Read-only list of captured signals, newest first. */
export function ReportEntryList({ entries }: { entries: ReportEntry[] }) {
  const { t, i18n } = useTranslation('report');

  if (entries.length === 0) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">{t('technicalEmpty')}</p>;
  }

  return (
    <ul className="max-h-56 overflow-auto rounded-md border bg-card/40">
      {entries.map((entry) => (
        <EntryRow key={entry.id} entry={entry} language={i18n.language} />
      ))}
    </ul>
  );
}
