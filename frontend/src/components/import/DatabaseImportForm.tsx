import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Database } from 'lucide-react';
import { ApiError } from '@/api/client';
import { startDatabaseImport } from '@/api/ingest';
import { useDatabaseConnections, useDatabaseTables } from '@/components/import/hooks/use-ingest';
import type { CommitImportRequest, DatabaseImportRequest, DatabaseTable } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';

type Step = 'pick' | 'review' | 'committing' | 'tracking';

// A table with two spatial columns is listed once per column.
const rowKey = (table: DatabaseTable) =>
  `${table.schema_name}.${table.table_name}.${table.geometry_column}`;

export function DatabaseImportForm() {
  const { t } = useTranslation('import');
  const id = useId();
  const { data: connections = [], isLoading: connectionsLoading } = useDatabaseConnections();
  const [chosenConnection, setChosenConnection] = useState<string | null>(null);
  // A lone connection needs no choosing.
  const connection = chosenConnection ?? (connections.length === 1 ? connections[0].name : null);
  const { data: listing, isLoading, error: listError, refetch } = useDatabaseTables(connection);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [step, setStep] = useState<Step>('pick');
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const tables = useMemo(() => listing?.tables ?? [], [listing]);
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle
      ? tables.filter((row) => `${row.schema_name}.${row.table_name}`.toLowerCase().includes(needle))
      : tables;
  }, [tables, filter]);
  const selected = tables.find((row) => rowKey(row) === selectedKey) ?? null;

  const reset = () => {
    setStep('pick');
    setJobId(null);
    setError(null);
    setSelectedKey(null);
  };

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (!connection || !selected) return;
    setStep('committing');
    setError(null);
    try {
      const response = await startDatabaseImport(connection, {
        schema_name: selected.schema_name,
        table_name: selected.table_name,
        title: metadata.title,
        summary: metadata.summary,
        visibility: (metadata.visibility ?? 'private') as DatabaseImportRequest['visibility'],
        srid_override: selected.srid === null ? metadata.srid_override : null,
      });
      setJobId(response.job_id);
      setStep('tracking');
    } catch (err) {
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
    }
  };

  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  if ((step === 'review' || step === 'committing') && selected) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('database.reviewing', {
            connection,
            table: `${selected.schema_name}.${selected.table_name}`,
          })}
        </p>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={selected.table_name}
          detectedCrs={selected.srid}
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
                  setSelectedKey(null);
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
                          selectedKey === key && 'bg-primary/10',
                        )}
                      >
                        <input
                          type="radio"
                          name={`${id}-table`}
                          checked={selectedKey === key}
                          onChange={() => setSelectedKey(key)}
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
              {selected?.srid === null && (
                <p className="text-xs text-muted-foreground">{t('database.srsNeeded')}</p>
              )}
              <Button disabled={!selected} onClick={() => setStep('review')}>
                {t('database.continue')}
              </Button>
            </>
          )}
        </>
      )}
    </div>
  );
}
