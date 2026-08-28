import { Fragment, useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useSearchParams } from 'react-router';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useAdminJobs, useCancelAdminJob, useRetryAdminJob, useUserNames } from '@/hooks/use-admin';
import { formatDate } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { jobStatusColors } from '@/lib/status-colors';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { DataTablePagination } from './DataTablePagination';
import { SortableColumnHeader, type SortDirection } from './SortableColumnHeader';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { FilterSelect } from './FilterSelect';
import { ErrorState } from '@/components/layout/ErrorState';

const PAGE_SIZE = 25;

/** Mirrors the JobSortField allowlist on GET /admin/jobs/. The retry control
 *  is absent by design: it is computed per page after the query, so a header
 *  for it would sort only the visible page, which looks correct and is not. */
const SORTABLE_FIELDS = [
  'created_at',
  'username',
  'source_filename',
  'status',
  'duration',
] as const;
type SortField = (typeof SORTABLE_FIELDS)[number];

const DEFAULT_SORT: SortField = 'created_at';
const DEFAULT_ORDER: SortDirection = 'desc';

function parseSortField(raw: string | null): SortField {
  return SORTABLE_FIELDS.includes(raw as SortField) ? (raw as SortField) : DEFAULT_SORT;
}

function parseSortOrder(raw: string | null): SortDirection {
  return raw === 'desc' || raw === 'asc' ? raw : DEFAULT_ORDER;
}

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
  // fix(#1185): the admin sidebar's failed-jobs badge links here as
  // /admin/jobs?status=failed so the number the user clicked equals the number
  // the list shows. Status therefore lives in the URL rather than in component
  // state — that also makes a filtered view bookmarkable and the back button
  // work. An unrecognized value falls back to "all statuses" instead of being
  // forwarded to the API.
  const [searchParams, setSearchParams] = useSearchParams();
  const { key: locationKey } = useLocation();
  const statusParam = searchParams.get('status') ?? '';
  const status = STATUS_OPTIONS.some((opt) => opt.value === statusParam) ? statusParam : '';
  // Set just before this component writes the status param itself, so the
  // effect below can tell an in-component dropdown change from an external
  // navigation. Always cleared by that effect, because a `replace: true`
  // write still produces a new location key (measured) — so the effect is
  // guaranteed to run and the flag cannot go stale.
  const isSelfWrite = useRef(false);
  const setStatus = useCallback(
    (next: string) => {
      isSelfWrite.current = true;
      setSearchParams(
        (params) => {
          if (next) params.set('status', next);
          else params.delete('status');
          return params;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  // Sort lives in the URL alongside status, so a sorted view is shareable.
  // Sort clicks REPLACE the history entry rather than pushing — deliberately,
  // per the #1200 review: pushing would make five header clicks cost five Back
  // presses to leave the page, and it matches this component's own
  // replace-on-refinement pattern (#1185). The trade is that Back leaves the
  // page instead of stepping through orderings. An unrecognised ?sort= falls
  // back to the default rather than erroring; the API refuses it independently.
  const sortField = parseSortField(searchParams.get('sort'));
  const sortOrder = parseSortOrder(searchParams.get('order'));

  const [userId, setUserId] = useState('');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // fix(#1185 review): arriving here from OUTSIDE this component — the sidebar
  // alert badge, a bookmark, the back button — must show the count the badge
  // advertised. React Router keeps this instance mounted for the same route,
  // so user/search/page would survive the navigation and silently narrow the
  // list below that number (status=failed AND user=alice AND skip=75 can
  // render zero rows while the badge says 3). That is the badge-vs-list
  // mismatch #1185 exists to remove, arriving through a second door.
  //
  // Keyed on `location.key`, NOT on the status value. Re-clicking the alert
  // while already at ?status=failed navigates to an identical URL, so a
  // value-keyed effect never fires and the stale filters survive — the same
  // defect one position over. `location.key` changes on every navigation
  // including a same-URL one (measured: 6g37p9up -> 25bb8de4).
  //
  // A dropdown change is deliberately exempt, since combining status with an
  // existing user or search filter is the point of the dropdown. Its own
  // `replace: true` write also produces a new key (measured), so this effect
  // always runs afterwards and always clears the flag — it cannot go stale
  // and swallow the next external navigation.
  useEffect(() => {
    if (isSelfWrite.current) {
      isSelfWrite.current = false;
      return;
    }
    setUserId('');
    setSearchQuery('');
    setPage(0);
  }, [locationKey]);

  function handleSort(field: string) {
    // Compare against the EFFECTIVE field, not the raw param: with no ?sort=
    // the Created column already renders as the active descending sort, so
    // clicking it must flip to ascending rather than re-assert descending.
    const next = sortField === field && sortOrder === 'asc' ? 'desc' : 'asc';
    // fix(#1204): sorting is a refinement of the current view, so it takes the
    // same self-write exemption the status dropdown does. Without the flag the
    // effect above would read this write as an external navigation and clear
    // the user's search and user filters on every header click.
    isSelfWrite.current = true;
    setSearchParams(
      (params) => {
        params.set('sort', field);
        params.set('order', next);
        return params;
      },
      { replace: true },
    );
    // A new ordering renumbers every page, so page 3 of the old sort names
    // different rows under the new one.
    setPage(0);
  }

  const skip = page * PAGE_SIZE;

  const { data, isLoading, error, refetch } = useAdminJobs({
    status: status || undefined,
    user_id: userId || undefined,
    search: searchQuery || undefined,
    skip,
    limit: PAGE_SIZE,
    sort: sortField,
    order: sortOrder,
  });

  const { data: userNames } = useUserNames();
  const retryAdminJob = useRetryAdminJob();
  const cancelAdminJob = useCancelAdminJob();
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
        <CardTitle level={2} className="text-sm font-medium">{t('jobs.title')}</CardTitle>
        <CardAction>
          <DataTableSearch
            value={searchQuery}
            onChange={(v) => { setSearchQuery(v); setPage(0); }}
            placeholder={t('jobs.table.filename')}
          />
        </CardAction>
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
          <ErrorState message={t('jobs.errorLoading', { message: error.message })} onRetry={() => refetch()} />
        )}

        {/* Job entries */}
        {isLoading && !data ? (
          <Table aria-label={t('jobs.title')}>
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
                <Table aria-label={t('jobs.title')} containerFocusable={false}>
                <TableHeader>
                  <TableRow>
                    {/* The disclosure column has no data to order by. */}
                    <TableHead className="w-12">
                      <span className="sr-only">{t('jobs.table.details', { defaultValue: 'Details' })}</span>
                    </TableHead>
                    <SortableColumnHeader
                      label={t('jobs.table.createdAt')}
                      field="created_at"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('jobs.table.user')}
                      field="username"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('jobs.table.filename')}
                      field="source_filename"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('jobs.table.status')}
                      field="status"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    {/* Duration is displayed from started_at/completed_at but
                        ordered by the same interval in SQL, so the column and
                        the sort agree. */}
                    <SortableColumnHeader
                      label={t('jobs.table.duration')}
                      field="duration"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
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
                        <TableCell
                          className="max-w-[36vw] truncate sm:max-w-none"
                          title={job.source_filename ?? undefined}
                        >
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
                              {job.status === 'failed' && job.retry_reason && (
                                <p className="mb-2 text-xs text-muted-foreground">
                                  {job.retry_reason}
                                </p>
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
                              {job.status === 'failed' && job.can_retry && (
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
                              {/* feat(#1677): one-click cancel on active
                                  rows, Retry parity — no confirm dialog;
                                  the action is recoverable and data-safe
                                  under the backend's no-swap fence. */}
                              {(job.status === 'pending' || job.status === 'running') && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    cancelAdminJob.mutate(job.id);
                                  }}
                                  disabled={cancelAdminJob.isPending}
                                >
                                  {cancelAdminJob.isPending ? t('jobs.cancelling') : t('jobs.cancel')}
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
