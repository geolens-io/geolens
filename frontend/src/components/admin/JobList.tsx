import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAdminJobs, useRetryAdminJob, useUserList } from '@/hooks/use-admin';
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

  const { data: usersData } = useUserList(0, 200);
  const retryAdminJob = useRetryAdminJob();

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);

  function clearFilters() {
    setStatus('');
    setUserId('');
    setPage(0);
    setSearchQuery('');
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
              ...(usersData?.users.map((user) => ({ value: user.id, label: user.username })) ?? []),
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
                <TableHead>{t('jobs.table.createdAt')}</TableHead>
                <TableHead>{t('jobs.table.user')}</TableHead>
                <TableHead>{t('jobs.table.filename')}</TableHead>
                <TableHead>{t('jobs.table.status')}</TableHead>
                <TableHead>{t('jobs.table.duration')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <DataTableSkeleton columns={[
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
              <Table>
                <TableHeader>
                  <TableRow>
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
                        className="cursor-pointer"
                        tabIndex={0}
                        role="button"
                        aria-expanded={expandedId === job.id}
                        onClick={() =>
                          setExpandedId(expandedId === job.id ? null : job.id)
                        }
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setExpandedId(expandedId === job.id ? null : job.id);
                          }
                        }}
                      >
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
                          <TableCell colSpan={5}>
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
