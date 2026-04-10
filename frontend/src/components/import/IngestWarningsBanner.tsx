import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { IngestJobWarning, JobStatusResponse } from '@/types/api';

interface IngestWarningsBannerProps {
  job: Pick<
    JobStatusResponse,
    'warnings' | 'archive_failed' | 'temporal_parse_errors'
  >;
  className?: string;
}

function ReservedRenameBody({
  warning,
}: {
  warning: Extract<IngestJobWarning, { kind: 'reserved_rename' }>;
}) {
  const { t } = useTranslation('import');
  return (
    <div className="space-y-1">
      <p className="font-medium">{t('warnings.reservedRename.title')}</p>
      <p className="text-xs text-muted-foreground">
        {t('warnings.reservedRename.description')}
      </p>
      <ul className="mt-1 list-disc ps-4 text-xs">
        {warning.details.map((rename) => (
          <li key={`${rename.original}-${rename.renamed}`}>
            <code className="font-mono">{rename.original}</code>
            {' → '}
            <code className="font-mono">{rename.renamed}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DbfTruncationBody({
  warning,
}: {
  warning: Extract<IngestJobWarning, { kind: 'dbf_truncation_collision' }>;
}) {
  const { t } = useTranslation('import');
  return (
    <div className="space-y-1">
      <p className="font-medium">{t('warnings.dbfTruncation.title')}</p>
      <p className="text-xs text-muted-foreground">
        {t('warnings.dbfTruncation.description')}
      </p>
      <ul className="mt-1 list-disc ps-4 text-xs">
        {warning.details.map((collision) => (
          <li key={collision.truncated}>
            <code className="font-mono">{collision.truncated}</code>
            {': '}
            {collision.originals.join(', ')}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Surface structured ingest warnings to the user. Rendered on the upload
 * success screen (JobProgress) so operators can see silent pipeline rewrites
 * (reserved-name renames, Shapefile DBF truncation, etc.) and fix their
 * source data before re-uploading. S3 follow-up from post-impl audit.
 */
export function IngestWarningsBanner({
  job,
  className,
}: IngestWarningsBannerProps) {
  const { t } = useTranslation('import');
  const warnings = job.warnings ?? [];
  const temporalErrors = job.temporal_parse_errors ?? {};
  const hasTemporalErrors = Object.keys(temporalErrors).length > 0;
  const hasAny =
    warnings.length > 0 || job.archive_failed || hasTemporalErrors;

  if (!hasAny) {
    return null;
  }

  return (
    <div
      role="status"
      className={[
        'rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-sm text-yellow-900 dark:text-yellow-100',
        className ?? '',
      ]
        .join(' ')
        .trim()}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="flex-1 space-y-3">
          <p className="font-semibold">{t('warnings.bannerTitle')}</p>
          {warnings.map((warning, idx) => {
            if (warning.kind === 'reserved_rename') {
              return (
                <ReservedRenameBody
                  key={`reserved-${idx}`}
                  warning={warning}
                />
              );
            }
            if (warning.kind === 'dbf_truncation_collision') {
              return (
                <DbfTruncationBody key={`dbf-${idx}`} warning={warning} />
              );
            }
            return null;
          })}
          {job.archive_failed && (
            <div className="space-y-1">
              <p className="font-medium">{t('warnings.archiveFailed.title')}</p>
              <p className="text-xs text-muted-foreground">
                {t('warnings.archiveFailed.description')}
              </p>
            </div>
          )}
          {hasTemporalErrors && (
            <div className="space-y-1">
              <p className="font-medium">
                {t('warnings.temporalParseErrors.title')}
              </p>
              <p className="text-xs text-muted-foreground">
                {t('warnings.temporalParseErrors.description')}
              </p>
              <ul className="mt-1 list-disc ps-4 text-xs">
                {Object.entries(temporalErrors).map(([field, rawValue]) => (
                  <li key={field}>
                    <code className="font-mono">{field}</code>
                    {': '}
                    <code className="font-mono">{rawValue}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
