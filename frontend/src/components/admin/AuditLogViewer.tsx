import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useAuditLogs } from '@/hooks/use-admin';
import { useEdition } from '@/hooks/use-edition';
import { formatDateTimeSmart } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { DataTablePagination } from './DataTablePagination';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { ExportSplitButton } from './ExportSplitButton';
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
  const { isEnterprise } = useEdition();
  const [action, setAction] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const toggleRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const skip = page * PAGE_SIZE;

  const { data, isLoading, error } = useAuditLogs({
    action: action || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    search: searchQuery || undefined,
    skip,
    limit: PAGE_SIZE,
  });

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);
  const visibleLogIds = data?.logs?.map((log) => log.id) ?? [];
  const [focusedToggleId, setFocusedToggleId] = useState<string | null>(null);

  useEffect(() => {
    const nextVisibleLogIds = data?.logs?.map((log) => log.id) ?? [];
    setFocusedToggleId((current) => {
      if (nextVisibleLogIds.length === 0) return null;
      return current && nextVisibleLogIds.includes(current) ? current : nextVisibleLogIds[0];
    });
  }, [data?.logs]);

  function clearFilters() {
    setAction('');
    setDateFrom('');
    setDateTo('');
    setPage(0);
    setSearchQuery('');
  }

  function moveDisclosureFocus(currentId: string, key: 'ArrowDown' | 'ArrowUp' | 'Home' | 'End') {
    if (visibleLogIds.length === 0) return;

    const currentIndex = visibleLogIds.indexOf(currentId);
    if (currentIndex === -1) return;

    let nextIndex = currentIndex;
    if (key === 'ArrowDown') {
      nextIndex = Math.min(currentIndex + 1, visibleLogIds.length - 1);
    } else if (key === 'ArrowUp') {
      nextIndex = Math.max(currentIndex - 1, 0);
    } else if (key === 'Home') {
      nextIndex = 0;
    } else if (key === 'End') {
      nextIndex = visibleLogIds.length - 1;
    }

    const nextId = visibleLogIds[nextIndex];
    setFocusedToggleId(nextId);
    toggleRefs.current[nextId]?.focus();
  }

  function handleDisclosureKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    logId: string,
  ) {
    if (
      event.key !== 'ArrowDown' &&
      event.key !== 'ArrowUp' &&
      event.key !== 'Home' &&
      event.key !== 'End'
    ) {
      return;
    }

    event.preventDefault();
    moveDisclosureFocus(event.currentTarget.dataset.logId ?? logId, event.key);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium">{t('audit.title')}</CardTitle>
          <div className="flex items-center gap-2">
            {isEnterprise && (
              <ExportSplitButton
                filters={{
                  action: action || undefined,
                  date_from: dateFrom || undefined,
                  date_to: dateTo || undefined,
                  search: searchQuery || undefined,
                }}
              />
            )}
            <DataTableSearch
              value={searchQuery}
              onChange={(v) => { setSearchQuery(v); setPage(0); }}
              placeholder={t('audit.table.user') + ' / ' + t('audit.table.action')}
            />
          </div>
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
                <TableHead className="w-12">
                  <span className="sr-only">{t('audit.table.details', { defaultValue: 'Details' })}</span>
                </TableHead>
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
                { width: 'w-8' },
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
              <>
                <p className="text-xs text-muted-foreground">
                  {t('audit.table.keyboardHint', {
                    defaultValue: 'Tab to the details control, then use Up and Down arrows to move between rows.',
                  })}
                </p>
                <Table containerFocusable={false}>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">
                      <span className="sr-only">{t('audit.table.details', { defaultValue: 'Details' })}</span>
                    </TableHead>
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
                        data-state={expandedId === log.id ? 'selected' : undefined}
                      >
                        <TableCell>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            data-testid="audit-details-toggle"
                            data-log-id={log.id}
                            aria-expanded={expandedId === log.id}
                            aria-label={
                              expandedId === log.id
                                ? t('audit.hideDetails', {
                                    defaultValue: 'Hide details for {{action}}',
                                    action: log.action,
                                  })
                                : t('audit.showDetails', {
                                    defaultValue: 'Show details for {{action}}',
                                    action: log.action,
                                  })
                            }
                            onClick={() =>
                              setExpandedId(expandedId === log.id ? null : log.id)
                            }
                            onFocus={() => setFocusedToggleId(log.id)}
                            onKeyDown={(event) => handleDisclosureKeyDown(event, log.id)}
                            tabIndex={focusedToggleId === log.id ? 0 : -1}
                            ref={(node) => {
                              toggleRefs.current[log.id] = node;
                            }}
                          >
                            {expandedId === log.id ? (
                              <ChevronDown className="size-4" />
                            ) : (
                              <ChevronRight className="size-4" />
                            )}
                          </Button>
                        </TableCell>
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
                          <TableCell colSpan={7}>
                            <div className="rounded-md bg-muted/50 p-3">
                              <p className="mb-1 text-xs font-medium text-muted-foreground">
                                {t('audit.detailsDescription', { defaultValue: 'Expanded log details' })}
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
              </>
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
