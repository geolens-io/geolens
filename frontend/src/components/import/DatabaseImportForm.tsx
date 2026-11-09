import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Database } from 'lucide-react';
import { ApiError } from '@/api/client';
import {
  beginDatabaseImport,
  clearDatabaseImport,
  peekDatabaseImport,
} from '@/api/database-import-session';
import { useDatabaseConnections, useDatabaseTables } from '@/components/import/hooks/use-ingest';
import type { CommitImportRequest, DatabaseImportRequest, DatabaseTable } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';

type Step = 'pick' | 'review' | 'committing' | 'tracking';

const rowKey = (table: DatabaseTable) => `${table.schema_name}.${table.table_name}`;

export function DatabaseImportForm() {
  const { t } = useTranslation('import');
  const id = useId();
  const { data: connections = [], isLoading: connectionsLoading } = useDatabaseConnections();
  // A request started before a tab switch is adopted rather than lost.
  const [adopted] = useState(peekDatabaseImport);
  const [chosenConnection, setChosenConnection] = useState<string | null>(adopted?.connection ?? null);
  // A lone connection needs no choosing.
  const connection = chosenConnection ?? (connections.length === 1 ? connections[0].name : null);
  const { data: listing, isLoading, error: listError, refetch } = useDatabaseTables(connection);
  const [choice, setChoice] = useState<DatabaseTable | null>(adopted?.table ?? null);
  const [filter, setFilter] = useState('');
  const [step, setStep] = useState<Step>(
    !adopted ? 'pick' : adopted.status === 'fulfilled' ? 'tracking' : adopted.status === 'rejected' ? 'review' : 'committing',
  );
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(adopted?.jobId ?? null);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const tables = listing?.tables ?? [];
    return needle
      ? tables.filter((row) => `${row.schema_name}.${row.table_name}`.toLowerCase().includes(needle))
      : tables;
  }, [listing, filter]);

  const reset = () => {
    clearDatabaseImport();
    setStep('pick');
    setJobId(null);
    setError(null);
    setChoice(null);
  };

  const fail = (err: unknown) => {
    clearDatabaseImport();
    setStep('review');
    if (err instanceof ApiError && err.status === 409) {
      const body = err.body as { code?: string; existing_dataset_id?: string; existing_title?: string } | undefined;
      if (body?.code === 'duplicate_source' && body.existing_dataset_id) {
        const msg = t('serviceUrl.alreadyRegistered', {
          title: body.existing_title ?? t('serviceUrl.unknownDataset'),
        });
        setError(msg);
        toast.error(msg, {
          action: {
            label: t('serviceUrl.viewExisting'),
            onClick: () => { window.location.href = `/datasets/${body.existing_dataset_id}`; },
          },
        });
        return;
      }
    }
    const msg = err instanceof ApiError ? err.message : t('database.importFailed');
    setError(msg);
    toast.error(msg);
  };

  const track = (promise: Promise<{ job_id: string }>) =>
    promise.then(
      (response) => {
        if (!mountedRef.current) return;
        setJobId(response.job_id);
        setStep('tracking');
      },
      (err) => {
        if (mountedRef.current) fail(err);
      },
    );

  useEffect(() => {
    if (!adopted) return;
    if (adopted.status === 'rejected') fail(adopted.error);
    else if (adopted.status === 'pending') void track(adopted.promise);
    // Adopted once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (!connection || !choice) return;
    setStep('committing');
    setError(null);
    const session = beginDatabaseImport(connection, choice, {
      schema_name: choice.schema_name,
      table_name: choice.table_name,
      title: metadata.title,
      summary: metadata.summary,
      visibility: (metadata.visibility ?? 'private') as DatabaseImportRequest['visibility'],
      srid_override: choice.srid === null ? metadata.srid_override : null,
    });
    await track(session.promise);
  };

  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  if ((step === 'review' || step === 'committing') && choice) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('database.reviewing', {
            connection,
            table: `${choice.schema_name}.${choice.table_name}`,
          })}
        </p>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={choice.table_name}
          detectedCrs={choice.srid}
          onCommit={handleCommit}
          isCommitting={step === 'committing'}
        />
        <Button variant="outline" onClick={() => setStep('pick')} disabled={step === 'committing'}>
          {t('database.back')}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5 rounded-xl border border-border bg-card p-5">
      {connectionsLoading && (
        <p role="status" className="text-sm text-muted-foreground">{t('database.loadingConnections')}</p>
      )}

      {connections.length > 1 && (
        <fieldset className="space-y-2">
          <legend className="eyebrow mb-1">{t('database.connection')}</legend>
          {connections.map((entry) => (
            <label key={entry.name} className="flex cursor-pointer items-center gap-2.5 text-sm">
              <input
                type="radio"
                name={`${id}-connection`}
                checked={connection === entry.name}
                onChange={() => {
                  setChosenConnection(entry.name);
                  setChoice(null);
                }}
              />
              <span className="font-medium">{entry.name}</span>
              <span className="text-xs text-muted-foreground">{entry.database}</span>
            </label>
          ))}
        </fieldset>
      )}

      {connection && isLoading && (
        <p role="status" className="text-sm text-muted-foreground">{t('database.loadingTables')}</p>
      )}

      {listError && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {listError instanceof ApiError ? listError.message : t('database.listFailed')}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            {t('database.retry')}
          </Button>
        </div>
      )}

      {listing && (
        <>
          {listing.tables.length === 0 ? (
            <div className="py-6 text-center">
              <Database className="mx-auto mb-3 size-8 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">
                {t('database.noTables', { database: listing.database })}
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-1.5">
                <label htmlFor={`${id}-filter`} className="eyebrow block">
                  {t('database.filterLabel')}
                </label>
                <Input
                  id={`${id}-filter`}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t('database.filterPlaceholder')}
                />
              </div>
              <fieldset className="space-y-1">
                <legend className="eyebrow mb-1">
                  {t('database.tablesLegend', { database: listing.database })}
                </legend>
                <div className="max-h-96 divide-y divide-border overflow-y-auto rounded-lg border border-border">
                  {visible.map((row) => {
                    const key = rowKey(row);
                    return (
                      <label
                        key={key}
                        className={cn(
                          'flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-surface-2',
                          choice !== null && rowKey(choice) === key && 'bg-primary/10',
                        )}
                      >
                        <input
                          type="radio"
                          name={`${id}-table`}
                          checked={choice !== null && rowKey(choice) === key}
                          onChange={() => setChoice(row)}
                        />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">
                          {row.schema_name}.{row.table_name}
                          <span className="text-muted-foreground"> ({row.geometry_column})</span>
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {row.object_type === 'view' ? t('database.view') : t('database.table')}
                        </span>
                        <span className="w-24 text-end font-mono text-xs text-muted-foreground">
                          {row.srid === null ? t('database.noSrid') : `EPSG:${row.srid}`}
                        </span>
                      </label>
                    );
                  })}
                </div>
                {visible.length === 0 && (
                  <p role="status" className="text-xs text-muted-foreground">{t('database.noMatches')}</p>
                )}
              </fieldset>
              {listing.truncated && (
                <p role="status" className="text-xs text-muted-foreground">
                  {t('database.truncated', { limit: listing.limit })}
                </p>
              )}
              {choice?.srid === null && (
                <p className="text-xs text-muted-foreground">{t('database.srsNeeded')}</p>
              )}
              <Button disabled={!choice} onClick={() => setStep('review')}>
                {t('database.continue')}
              </Button>
            </>
          )}
        </>
      )}
    </div>
  );
}
