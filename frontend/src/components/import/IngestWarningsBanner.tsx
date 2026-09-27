import { useId, useState } from 'react';
import { AlertTriangle, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { IngestJobWarning, JobStatusResponse } from '@/types/api';

interface IngestWarningsBannerProps {
  job: Pick<
    JobStatusResponse,
    'warnings' | 'archive_failed' | 'temporal_parse_errors'
  >;
  className?: string;
  compact?: boolean;
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

function MercatorClipBody({
  warning,
}: {
  warning: Extract<IngestJobWarning, { kind: 'mercator_clip' }>;
}) {
  const { t } = useTranslation('import');
  const {
    dropped_features: dropped,
    clipped_features: clipped,
    clip_skipped: skipped,
  } = warning.details;
  return (
    <div className="space-y-1">
      <p className="font-medium">{t('warnings.mercatorClip.title')}</p>
      <p className="text-xs text-muted-foreground">
        {t(
          skipped
            ? 'warnings.mercatorClip.skippedDescription'
            : 'warnings.mercatorClip.description',
        )}
      </p>
      <ul className="mt-1 list-disc ps-4 text-xs">
        {dropped > 0 && (
          <li>{t('warnings.mercatorClip.dropped', { count: dropped })}</li>
        )}
        {clipped > 0 && (
          <li>{t('warnings.mercatorClip.clipped', { count: clipped })}</li>
        )}
      </ul>
    </div>
  );
}

export function IngestWarningsBanner({
  job,
  className,
  compact = false,
}: IngestWarningsBannerProps) {
  const { t } = useTranslation('import');
  const [expanded, setExpanded] = useState(!compact);
  const detailsId = useId();
  const warnings = job.warnings ?? [];
  const temporalErrors = job.temporal_parse_errors ?? {};
  const hasTemporalErrors = Object.keys(temporalErrors).length > 0;
  const hasAny =
    warnings.length > 0 || job.archive_failed || hasTemporalErrors;
  const count = warnings.length + Number(!!job.archive_failed) + Number(hasTemporalErrors);
  const hasDataLoss = warnings.some((warning) =>
    warning.kind === 'dbf_truncation_collision' ||
    (warning.kind === 'mercator_clip' && warning.details.dropped_features > 0),
  ) || hasTemporalErrors;

  if (!hasAny) {
    return null;
  }

  return (
    <div
      role="status"
      className={[
        'rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-foreground',
        className ?? '',
      ]
        .join(' ')
        .trim()}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle
          className="mt-0.5 size-4 shrink-0 text-warning"
          aria-hidden="true"
        />
        <div className="flex-1 space-y-3">
          {compact ? (
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={detailsId}
              onClick={() => setExpanded((value) => !value)}
              className="flex w-full items-center justify-between gap-2 rounded-sm text-start font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span>{job.archive_failed
                ? t('warnings.compactArchiveFailure', { count })
                : t(hasDataLoss ? 'warnings.compactDataLoss' : 'warnings.compactSummary', { count })}</span>
              <ChevronDown className={`size-4 shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>
          ) : <p className="font-semibold">{t('warnings.bannerTitle')}</p>}
          <div id={detailsId} hidden={!expanded} className="space-y-3">
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
              if (warning.kind === 'mercator_clip') {
                return (
                  <MercatorClipBody key={`mercator-${idx}`} warning={warning} />
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
    </div>
  );
}
