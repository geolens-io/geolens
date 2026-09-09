import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { formatDateTimeSmart } from '@/lib/format';
import type { EmbeddingStatsResponse } from '@/types/api';

/**
 * Progress, before-start estimate and recent history for the embedding backfill.
 *
 * Reads everything off the coverage response the AI settings panel already
 * holds, so an operator who reloads mid-run still sees the run they started.
 */
export function BackfillRunStatus({ stats }: { stats: EmbeddingStatsResponse }) {
  const { t } = useTranslation('admin');
  const run = stats.current_run;
  const total = run?.records_total ?? null;
  const percent =
    run && total ? Math.min(100, Math.round((run.records_processed / total) * 100)) : 0;

  if (!run && !stats.estimate && stats.recent_runs.length === 0) return null;

  return (
    <div className="space-y-3 border-t pt-3">
      {run && (
        <div className="space-y-1.5" data-testid="backfill-progress">
          <div className="flex items-center justify-between text-xs">
            <span>{t('ai.backfillInProgress')}</span>
            <span className="text-muted-foreground tabular-nums">
              {total === null
                ? t('ai.backfillStarting')
                : t('ai.backfillProgress', { processed: run.records_processed, total })}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              data-testid="backfill-progress-bar"
              className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      )}

      {/* An estimate describes a run the operator has not started yet, so it
          steps aside while one is in flight and the bar above answers instead. */}
      {!run && stats.estimate && (
        <div className="space-y-0.5 text-xs text-muted-foreground">
          {stats.missing_records > 0 && (
            <p>
              {t('ai.estimateGenerateMissing', {
                count: estimateMinutes(stats.estimate.missing_seconds),
              })}
            </p>
          )}
          {stats.total_records > 0 && (
            <p>
              {t('ai.estimateRegenerateAll', {
                count: estimateMinutes(stats.estimate.all_seconds),
              })}
            </p>
          )}
        </div>
      )}

      {stats.recent_runs.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium">{t('ai.recentRuns')}</p>
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {stats.recent_runs.map((entry) => (
              <li key={entry.job_id} className="flex items-baseline justify-between gap-2">
                <span className="truncate">
                  {outcomeLabel(t, entry.status)}
                  {entry.error_code ? ` (${entry.error_code})` : ''}
                  {' · '}
                  {t('ai.runRecords', { count: entry.records_processed })}
                </span>
                <span className="tabular-nums whitespace-nowrap">
                  {formatDateTimeSmart(entry.finished_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Never rounds down to zero: a short run still took a moment, not no time. */
function estimateMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

function outcomeLabel(t: TFunction<'admin'>, status: string): string {
  if (status === 'complete') return t('ai.runOutcomeComplete');
  if (status === 'cancelled') return t('ai.runOutcomeCancelled');
  return t('ai.runOutcomeFailed');
}
