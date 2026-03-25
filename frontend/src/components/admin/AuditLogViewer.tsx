import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuditLogs } from '@/hooks/use-admin';
import { formatDateTimeSmart } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { DataTablePagination } from './DataTablePagination';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { FilterSelect } from './FilterSelect';
import { ErrorState } from '@/components/layout/ErrorState';

const PAGE_SIZE = 25;

const ACTION_OPTIONS = [
  { value: '', labelKey: 'audit.filters.allActions' },
  { value: 'dataset.view', labelKey: 'audit.filters.datasetView' },
  { value: 'dataset.export', labelKey: 'audit.filters.datasetExport' },
  { value: 'metadata.edit', labelKey: 'audit.filters.metadataEdit' },
  { value: 'dataset.create', labelKey: 'audit.filters.datasetCreate' },
  { value: 'dataset.delete', labelKey: 'audit.filters.datasetDelete' },
];

export function AuditLogViewer() {
  const { t } = useTranslation('admin');
  const [action, setAction] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const skip = page * PAGE_SIZE;

  const { data, isLoading, error } = useAuditLogs({
    action: action || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    search: searchQuery || undefined,
    skip,
    limit: PAGE_SIZE,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const rangeStart = data && data.total > 0 ? skip + 1 : 0;
  const rangeEnd = data ? Math.min(skip + PAGE_SIZE, data.total) : 0;

  function clearFilters() {
    setAction('');
    setDateFrom('');
    setDateTo('');
    setPage(0);
    setSearchQuery('');
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{t('audit.title')}</CardTitle>
          <DataTableSearch
            value={searchQuery}
            onChange={(v) => { setSearchQuery(v); setPage(0); }}
            placeholder={t('audit.table.user') + ' / ' + t('audit.table.action')}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <FilterSelect
            label={t('audit.filters.action')}
            value={action}
            onChange={(v) => { setAction(v); setPage(0); }}
            options={ACTION_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey) }))}
          />
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.from')}
            </label>
            <Input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(0);
              }}
              className="h-8 w-40"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.to')}
            </label>
            <Input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(0);
              }}
              className="h-8 w-40"
            />
          </div>
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            {t('audit.filters.clear')}
          </Button>
        </div>

        {/* Error */}
        {error && (
          <ErrorState message={t('audit.errorLoading', { message: error.message })} />
        )}

        {/* Loading skeleton */}
        {isLoading && !data ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('audit.table.timestamp')}</TableHead>
                <TableHead>{t('audit.table.user')}</TableHead>
                <TableHead>{t('audit.table.action')}</TableHead>
                <TableHead>{t('audit.table.resource')}</TableHead>
                <TableHead>{t('audit.table.resourceId')}</TableHead>
                <TableHead>{t('audit.table.ipAddress')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <DataTableSkeleton columns={[
                { width: 'w-28' },
                { width: 'w-20' },
                { width: 'w-24', rounded: true },
                { width: 'w-16' },
                { width: 'w-20' },
                { width: 'w-24' },
              ]} />
            </TableBody>
          </Table>
        ) : data ? (
          <>
            {data.logs.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t('audit.noLogs')}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('audit.table.timestamp')}</TableHead>
                    <TableHead>{t('audit.table.user')}</TableHead>
                    <TableHead>{t('audit.table.action')}</TableHead>
                    <TableHead>{t('audit.table.resource')}</TableHead>
                    <TableHead>{t('audit.table.resourceId')}</TableHead>
                    <TableHead>{t('audit.table.ipAddress')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.logs ?? []).map((log) => (
                    <Fragment key={log.id}>
                      <TableRow
                        className="cursor-pointer"
                        onClick={() =>
                          setExpandedId(expandedId === log.id ? null : log.id)
                        }
                      >
                        <TableCell className="whitespace-nowrap">
                          {formatDateTimeSmart(log.created_at)}
                        </TableCell>
                        <TableCell>
                          {log.username ?? '-'}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">
                            {log.action}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {log.resource_type ?? '-'}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {log.resource_id
                            ? log.resource_id.slice(0, 8) + '...'
                            : '-'}
                        </TableCell>
                        <TableCell>{log.ip_address ?? '-'}</TableCell>
                      </TableRow>
                      {expandedId === log.id && (
                        <TableRow>
                          <TableCell colSpan={6}>
                            <div className="rounded-md bg-muted/50 p-3">
                              <p className="mb-1 text-xs font-medium text-muted-foreground">
                                {t('audit.detailsHint')}
                              </p>
                              <pre className="overflow-x-auto text-xs">
                                {JSON.stringify(log.details ?? {}, null, 2)}
                              </pre>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            )}

            <DataTablePagination
              page={page}
              totalPages={totalPages}
              rangeStart={rangeStart}
              rangeEnd={rangeEnd}
              total={data.total}
              onPageChange={setPage}
            />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
