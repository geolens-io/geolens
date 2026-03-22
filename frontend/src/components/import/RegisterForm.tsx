import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useDiscoverTables, useBulkRegister } from '@/hooks/use-ingest';
import type { BulkRegisterResult } from '@/types/api';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { TablePicker } from './TablePicker';
import { CheckCircle2, XCircle } from 'lucide-react';

const VISIBILITY_OPTIONS = [
  { value: 'private', labelKey: 'register.visibilityPrivate' },
  { value: 'restricted', labelKey: 'register.visibilityRestricted' },
  { value: 'public', labelKey: 'register.visibilityPublic' },
];

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

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibility, setVisibility] = useState('private');
  const [results, setResults] = useState<BulkRegisterResult[] | null>(null);

  const tables = data?.tables ?? [];

  function handleToggle(tableName: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(tableName)) {
        next.delete(tableName);
      } else {
        next.add(tableName);
      }
      return next;
    });
  }

  function handleToggleAll() {
    if (selected.size === tables.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(tables.map((t) => t.table_name)));
    }
  }

  async function handleRegister() {
    const request = {
      tables: tables
        .filter((t) => selected.has(t.table_name))
        .map((t) => ({
          table_name: t.table_name,
          title: toDisplayName(t.table_name),
          visibility,
        })),
    };

    try {
      const response = await bulkRegister.mutateAsync(request);
      setResults(response.results);

      const successes = response.results.filter((r) => r.status === 'success');
      const errors = response.results.filter((r) => r.status === 'error');

      if (errors.length > 0) {
        toast.error(t('register.failedToast', { count: errors.length }));
      }

      if (successes.length > 0) {
        toast.success(t('register.successToast', { count: successes.length }));
      }

      await queryClient.invalidateQueries({ queryKey: ['discover-tables'] });

      // Single success with no errors: navigate directly
      if (successes.length === 1 && errors.length === 0 && successes[0].dataset_id) {
        navigate(`/datasets/${successes[0].dataset_id}`);
      }
    } catch {
      toast.error(t('register.registerFailed'));
    }
  }

  function handleRegisterMore() {
    setResults(null);
    setSelected(new Set());
    queryClient.invalidateQueries({ queryKey: ['discover-tables'] });
  }

  // Results view
  if (results) {
    const successes = results.filter((r) => r.status === 'success');
    const errors = results.filter((r) => r.status === 'error');

    return (
      <Card>
        <CardContent className="space-y-4">
          <h3 className="text-sm font-semibold">{t('register.resultsTitle')}</h3>

          {successes.length > 0 && (
            <div className="space-y-1.5">
              {successes.map((r) => (
                <div
                  key={r.table_name}
                  className="flex items-center gap-2 text-sm"
                >
                  <CheckCircle2 className="h-4 w-4 text-success shrink-0" />
                  <span className="font-mono">{r.table_name}</span>
                  {r.dataset_id && (
                    <a
                      href={`/datasets/${r.dataset_id}`}
                      onClick={(e) => {
                        e.preventDefault();
                        navigate(`/datasets/${r.dataset_id}`);
                      }}
                      className="text-primary underline underline-offset-4 text-xs ml-auto"
                    >
                      {t('register.viewDataset')}
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}

          {errors.length > 0 && (
            <div className="space-y-1.5">
              {errors.map((r) => (
                <div
                  key={r.table_name}
                  className="flex items-center gap-2 text-sm"
                >
                  <XCircle className="h-4 w-4 text-destructive shrink-0" />
                  <span className="font-mono">{r.table_name}</span>
                  {r.error && (
                    <span className="text-xs text-muted-foreground ml-auto">
                      {r.error}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          <Button variant="outline" onClick={handleRegisterMore}>
            {t('register.registerMore')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            {t('register.discovering')}
          </span>
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (discoverError) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-sm text-destructive">
            {t('register.discoverFailed')}{' '}
            {discoverError instanceof Error
              ? discoverError.message
              : t('register.unknownError')}
          </p>
        </CardContent>
      </Card>
    );
  }

  // Empty state
  if (tables.length === 0) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-sm text-muted-foreground text-center">
            {t('register.emptyState')}
          </p>
        </CardContent>
      </Card>
    );
  }

  // Table picker form
  return (
    <Card>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('register.helpText')}
        </p>

        <TablePicker
          tables={tables}
          selected={selected}
          onToggle={handleToggle}
          onToggleAll={handleToggleAll}
        />

        <div className="space-y-2">
          <Label htmlFor="visibility">{t('register.visibilityLabel')}</Label>
          <select
            id="visibility"
            value={visibility}
            onChange={(e) => setVisibility(e.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
          >
            {VISIBILITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground mt-1">
            {t('register.visibilityHelp')}
          </p>
        </div>

        <Button
          onClick={handleRegister}
          disabled={selected.size === 0 || bulkRegister.isPending}
        >
          {bulkRegister.isPending ? (
            <span className="flex items-center gap-2">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
              {t('register.registering')}
            </span>
          ) : (
            t('register.registerButton', { count: selected.size })
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
