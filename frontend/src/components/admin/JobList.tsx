import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useAdminJobs, useRetryAdminJob, useUserNames } from '@/hooks/use-admin';
import { formatDate } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { jobStatusColors } from '@/lib/status-colors';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { DataTablePagination } from './DataTablePagination';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { FilterSelect } from './FilterSelect';
import { ErrorState } from '@/components/layout/ErrorState';

const PAGE_SIZE = 25;

const STATUS_OPTIONS = [
  { value: '', labelKey: 'jobs.filters.allStatuses' },
  { value: 'pending', labelKey: 'jobs.filters.pending' },
  { value: 'running', labelKey: 'jobs.filters.running' },
  { value: 'complete', labelKey: 'jobs.filters.complete' },
  { value: 'failed', labelKey: 'jobs.filters.failed' },
];

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return '-';
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

export function JobList() {
  const { t } = useTranslation('admin');
  const [status, setStatus] = useState('');
  const [userId, setUserId] = useState('');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const skip = page * PAGE_SIZE;

  const { data, isLoading, error } = useAdminJobs({
    status: status || undefined,
    user_id: userId || undefined,
    search: searchQuery || undefined,
    skip,
    limit: PAGE_SIZE,
  });

  const { data: userNames } = useUserNames();
  const retryAdminJob = useRetryAdminJob();
  const toggleRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);
  const visibleJobIds = data?.jobs?.map((job) => job.id) ?? [];
  const [focusedToggleId, setFocusedToggleId] = useState<string | null>(null);

  useEffect(() => {
    const nextVisibleJobIds = data?.jobs?.map((job) => job.id) ?? [];
    setFocusedToggleId((current) => {
      if (nextVisibleJobIds.length === 0) return null;
      return current && nextVisibleJobIds.includes(current) ? current : nextVisibleJobIds[0];
    });
  }, [data?.jobs]);

  function clearFilters() {
    setStatus('');
    setUserId('');
    setPage(0);
    setSearchQuery('');
  }

  function moveDisclosureFocus(currentId: string, key: 'ArrowDown' | 'ArrowUp' | 'Home' | 'End') {
    if (visibleJobIds.length === 0) return;

    const currentIndex = visibleJobIds.indexOf(currentId);
    if (currentIndex === -1) return;

    let nextIndex = currentIndex;
    if (key === 'ArrowDown') {
      nextIndex = Math.min(currentIndex + 1, visibleJobIds.length - 1);
    } else if (key === 'ArrowUp') {
      nextIndex = Math.max(currentIndex - 1, 0);
    } else if (key === 'Home') {
      nextIndex = 0;
    } else if (key === 'End') {
      nextIndex = visibleJobIds.length - 1;
    }

    const nextId = visibleJobIds[nextIndex];
    setFocusedToggleId(nextId);
    toggleRefs.current[nextId]?.focus();
  }

  function handleDisclosureKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    jobId: string,
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
    moveDisclosureFocus(event.currentTarget.dataset.jobId ?? jobId, event.key);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{t('jobs.title')}</CardTitle>
          <DataTableSearch
            value={searchQuery}
            onChange={(v) => { setSearchQuery(v); setPage(0); }}
            placeholder={t('jobs.table.filename')}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <FilterSelect
            label={t('jobs.filters.status')}
            value={status}
            onChange={(v) => { setStatus(v); setPage(0); }}
            options={STATUS_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey) }))}
          />
          <FilterSelect
            label={t('jobs.filters.user')}
            value={userId}
            onChange={(v) => { setUserId(v); setPage(0); }}
            options={[
              { value: '', label: t('jobs.filters.allUsers') },
              ...(userNames?.map((u) => ({ value: u.id, label: u.username })) ?? []),
            ]}
          />
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            {t('jobs.filters.clear')}
          </Button>
        </div>

        {/* Error */}
        {error && (
          <ErrorState message={t('jobs.errorLoading', { message: error.message })} />
        )}

        {/* Job entries */}
        {isLoading && !data ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <span className="sr-only">{t('jobs.table.details', { defaultValue: 'Details' })}</span>
                </TableHead>
                <TableHead>{t('jobs.table.createdAt')}</TableHead>
                <TableHead>{t('jobs.table.user')}</TableHead>
                <TableHead>{t('jobs.table.filename')}</TableHead>
                <TableHead>{t('jobs.table.status')}</TableHead>
                <TableHead>{t('jobs.table.duration')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <DataTableSkeleton columns={[
                { width: 'w-8' },
                { width: 'w-28' },
                { width: 'w-20' },
                { width: 'w-32' },
                { width: 'w-16', rounded: true },
                { width: 'w-12' },
              ]} />
            </TableBody>
          </Table>
        ) : data ? (
          <>
            {data.jobs.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t('jobs.noJobs')}
              </p>
            ) : (
              <>
                <p className="text-xs text-muted-foreground">
                  {t('jobs.table.keyboardHint', {
                    defaultValue: 'Tab to the details control, then use Up and Down arrows to move between rows.',
                  })}
                </p>
                <Table containerFocusable={false}>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">
                      <span className="sr-only">{t('jobs.table.details', { defaultValue: 'Details' })}</span>
                    </TableHead>
                    <TableHead>{t('jobs.table.createdAt')}</TableHead>
                    <TableHead>{t('jobs.table.user')}</TableHead>
                    <TableHead>{t('jobs.table.filename')}</TableHead>
                    <TableHead>{t('jobs.table.status')}</TableHead>
                    <TableHead>{t('jobs.table.duration')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.jobs ?? []).map((job) => (
                    <Fragment key={job.id}>
                      <TableRow
                        data-state={expandedId === job.id ? 'selected' : undefined}
                      >
                        <TableCell>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            data-testid="job-details-toggle"
                            data-job-id={job.id}
                            aria-expanded={expandedId === job.id}
                            aria-label={
                              expandedId === job.id
                                ? t('jobs.hideDetails', {
                                    defaultValue: 'Hide details for {{name}}',
                                    name: job.source_filename ?? t('jobs.title'),
                                  })
                                : t('jobs.showDetails', {
                                    defaultValue: 'Show details for {{name}}',
                                    name: job.source_filename ?? t('jobs.title'),
                                  })
                            }
                            onClick={() =>
                              setExpandedId(expandedId === job.id ? null : job.id)
                            }
                            onFocus={() => setFocusedToggleId(job.id)}
                            onKeyDown={(event) => handleDisclosureKeyDown(event, job.id)}
                            tabIndex={focusedToggleId === job.id ? 0 : -1}
                            ref={(node) => {
                              toggleRefs.current[job.id] = node;
                            }}
                          >
                            {expandedId === job.id ? (
                              <ChevronDown className="size-4" />
                            ) : (
                              <ChevronRight className="size-4 rtl-mirror" />
                            )}
                          </Button>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {formatDate(job.created_at)}
                        </TableCell>
                        <TableCell>
                          {job.username ?? '-'}
                        </TableCell>
                        <TableCell>
                          {job.source_filename ?? '-'}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-xs ${jobStatusColors[job.status] ?? 'bg-muted text-muted-foreground border-border'}`}
                          >
                            {job.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {formatDuration(job.started_at, job.completed_at)}
                        </TableCell>
                      </TableRow>
                      {expandedId === job.id && (
                        <TableRow key={`${job.id}-detail`}>
                          <TableCell colSpan={6}>
                            <div className="rounded-md bg-muted/50 p-3">
                              {job.error_message && (
                                <div className="mb-2">
                                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                                    {t('jobs.detail.errorMessage')}
                                  </p>
                                  <pre className="whitespace-pre-wrap overflow-x-auto text-xs">
                                    {job.error_message}
                                  </pre>
                                </div>
                              )}
                              {job.user_metadata && (
                                <div className="mb-2">
                                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                                    {t('jobs.detail.userMetadata')}
                                  </p>
                                  <pre className="whitespace-pre-wrap overflow-x-auto text-xs">
                                    {JSON.stringify(job.user_metadata, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {job.status === 'failed' && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    retryAdminJob.mutate(job.id);
                                  }}
                                  disabled={retryAdminJob.isPending}
                                >
                                  {retryAdminJob.isPending ? t('jobs.retrying') : t('jobs.retry')}
                                </Button>
                              )}
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
