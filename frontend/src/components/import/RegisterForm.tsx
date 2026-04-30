import { useState } from 'react';
import { useNavigate, Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useDiscoverTables, useBulkRegister } from '@/components/import/hooks/use-ingest';
import { queryKeys } from '@/lib/query-keys';
import type { BulkRegisterResult, DiscoveredTable } from '@/types/api';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CheckCircle2, XCircle, Database, Search } from 'lucide-react';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { formatNumber } from '@/lib/format';

function toDisplayName(tableName: string): string {
  return tableName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function RegisterForm() {
  const { t } = useTranslation('import');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading, error: discoverError } = useDiscoverTables();
  const bulkRegister = useBulkRegister();

  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'restricted' | 'public'>('private');
  const [results, setResults] = useState<BulkRegisterResult[] | null>(null);

  const tables = data?.tables ?? [];
  const filtered = tables.filter((t) =>
    t.table_name.toLowerCase().includes(search.toLowerCase()),
  );
  const activeTable = tables.find((t) => t.table_name === selected) ?? null;

  function handleToggle(tableName: string) {
    setSelected((prev) => (prev === tableName ? null : tableName));
  }

  async function handleRegister() {
    if (!activeTable) return;

    try {
      const response = await bulkRegister.mutateAsync({
        tables: [{
          table_name: activeTable.table_name,
          title: toDisplayName(activeTable.table_name),
          visibility,
        }],
      });
      setResults(response.results);

      const successes = response.results.filter((r) => r.status === 'success');
      const errors = response.results.filter((r) => r.status === 'error');

      if (errors.length > 0) toast.error(t('register.failedToast', { count: errors.length }));
      if (successes.length > 0) toast.success(t('register.successToast', { count: successes.length }));

      await queryClient.invalidateQueries({ queryKey: queryKeys.ingest.discoverTables });

      if (successes.length === 1 && errors.length === 0 && successes[0].dataset_id) {
        navigate(`/datasets/${successes[0].dataset_id}`);
      }
    } catch {
      toast.error(t('register.registerFailed'));
    }
  }

  function handleRegisterMore() {
    setResults(null);
    setSelected(null);
    queryClient.invalidateQueries({ queryKey: queryKeys.ingest.discoverTables });
  }

  // ── Results view ──
  if (results) {
    const successes = results.filter((r) => r.status === 'success');
    const errors = results.filter((r) => r.status === 'error');

    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card p-5 space-y-4">
        <h3 className="text-sm font-semibold">{t('register.resultsTitle')}</h3>
        {successes.length > 0 && (
          <div className="space-y-1.5">
            {successes.map((r) => (
              <div key={r.table_name} className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-success shrink-0" />
                <span className="font-mono">{r.table_name}</span>
                {r.dataset_id && (
                  <Link
                    to={`/datasets/${r.dataset_id}`}
                    className="text-primary underline underline-offset-4 text-xs ms-auto"
                  >
                    {t('register.viewDataset')}
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
        {errors.length > 0 && (
          <div className="space-y-1.5">
            {errors.map((r) => (
              <div key={r.table_name} className="flex items-center gap-2 text-sm">
                <XCircle className="h-4 w-4 text-destructive shrink-0" />
                <span className="font-mono">{r.table_name}</span>
                {r.error && <span className="text-xs text-muted-foreground ms-auto">{r.error}</span>}
              </div>
            ))}
          </div>
        )}
        <Button variant="outline" onClick={handleRegisterMore}>
          {t('register.registerMore')}
        </Button>
      </div>
    );
  }

  // ── Loading ──
  if (isLoading) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-border bg-card py-12">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          {t('register.discovering')}
        </span>
      </div>
    );
  }

  // ── Error ──
  if (discoverError) {
    return (
      <div className="rounded-xl border border-border bg-card p-6">
        <p className="text-sm text-destructive">
          {t('register.discoverFailed')}
        </p>
      </div>
    );
  }

  // ── Empty ──
  if (tables.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card py-12 text-center">
        <Database className="mx-auto mb-3 size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{t('register.emptyState')}</p>
      </div>
    );
  }

  // ── Two-panel layout ──
  return (
    <div className="grid min-h-[420px] overflow-hidden rounded-xl border border-border bg-card md:grid-cols-[280px_1fr]">
      {/* Left sidebar */}
      <aside className="border-r border-border bg-surface-0 py-3">
        <div className="px-3 pb-2.5">
          <div className="relative">
            <Search className="absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('register.searchPlaceholder', { defaultValue: 'Search tables…' })}
              className="h-8 ps-8 text-[12.5px]"
            />
          </div>
        </div>

        <div className="px-3.5 py-1.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
          <Database className="size-2.5" />
          public · {filtered.length} tables
        </div>

        <div className="max-h-80 overflow-y-auto">
          {filtered.map((table) => (
            <button
              key={table.table_name}
              onClick={() => handleToggle(table.table_name)}
              className={cn(
                'grid w-full grid-cols-[14px_1fr_auto] items-center gap-2 px-3.5 py-1.5 text-start text-[12.5px] cursor-pointer',
                'hover:bg-surface-2',
                selected === table.table_name && 'bg-primary/10',
              )}
            >
              <Database className={cn('size-3', selected === table.table_name ? 'text-primary' : 'text-muted-foreground')} />
              <span className={cn('truncate', selected === table.table_name && 'text-primary font-semibold')}>
                {table.table_name}
              </span>
              <span className="font-mono text-[10.5px] text-muted-foreground tracking-wide">
                {table.estimated_rows != null ? formatNumber(table.estimated_rows) : '—'}
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* Right detail panel */}
      <div className="p-5">
        {activeTable ? (
          <TableDetail
            table={activeTable}
            visibility={visibility}
            onVisibilityChange={setVisibility}
            onRegister={handleRegister}
            isPending={bulkRegister.isPending}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {t('register.selectHint', { defaultValue: 'Select a table from the list to see its schema and register it.' })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Table detail panel ───────────────────────────────── */

function TableDetail({
  table,
  visibility,
  onVisibilityChange,
  onRegister,
  isPending,
}: {
  table: DiscoveredTable;
  visibility: string;
  onVisibilityChange: (v: string) => void;
  onRegister: () => void;
  isPending: boolean;
}) {
  const { t } = useTranslation('import');

  return (
    <>
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground mb-2.5">
        public / <span className="font-medium text-foreground normal-case">{table.table_name}</span>
      </p>
      <h2 className="text-xl font-medium tracking-tight mb-1.5">{table.table_name}</h2>
      <p className="text-[13px] text-muted-foreground mb-5 max-w-lg">
        {t('register.detailDesc', {
          defaultValue: 'Register to expose as a GeoLens dataset — tiled on the fly, no copy.',
        })}
      </p>

      {/* Stats grid */}
      <div className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
        {[
          { label: 'Rows', value: table.estimated_rows != null ? formatNumber(table.estimated_rows) : '—' },
          { label: 'Geometry', value: table.geometry_type ? getGeometryTypeLabel(t, table.geometry_type) : 'None' },
          { label: 'SRID', value: table.srid != null ? `EPSG:${table.srid}` : '—' },
          { label: 'Type', value: table.geometry_type ? 'Spatial' : 'Non-spatial' },
        ].map((stat) => (
          <div key={stat.label} className="bg-card px-3.5 py-2.5">
            <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">{stat.label}</dt>
            <dd className="text-sm font-medium tracking-tight">{stat.value}</dd>
          </div>
        ))}
      </div>

      {/* Actions */}
      <fieldset disabled={isPending} className="flex items-center gap-3 flex-wrap mt-5 disabled:opacity-60">
        <select
          value={visibility}
          onChange={(e) => onVisibilityChange(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
        >
          <option value="private">{t('register.visibilityPrivate')}</option>
          <option value="restricted">{t('register.visibilityRestricted')}</option>
          <option value="public">{t('register.visibilityPublic')}</option>
        </select>
        <Button onClick={onRegister} disabled={isPending}>
          {isPending ? (
            <span className="flex items-center gap-2">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
              {t('register.registering')}
            </span>
          ) : (
            t('register.registerButton', { count: 1, defaultValue: 'Register as dataset' })
          )}
        </Button>
      </div>
    </>
  );
}
