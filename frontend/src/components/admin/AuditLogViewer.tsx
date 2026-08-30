import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useAuditLogs } from '@/hooks/use-admin';
import { formatDateTimeSmart } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { DataTablePagination } from './DataTablePagination';
import { SortableColumnHeader, type SortDirection } from './SortableColumnHeader';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { ExportSplitButton } from './ExportSplitButton';
import { FilterSelect } from './FilterSelect';
import { ErrorState } from '@/components/layout/ErrorState';

const PAGE_SIZE = 25;
const UUID_PATTERN = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;

/** Mirrors the AuditSortField allowlist on GET /admin/audit-logs/. Resource
 *  name and resource id are absent by design: the name is resolved per page
 *  AFTER the query returns, and the id is an opaque uuid nobody orders by.
 *  A header for the name would sort only the visible page, which looks
 *  correct and is not. */
const SORTABLE_FIELDS = [
  'created_at',
  'username',
  'action',
  'resource_type',
  'ip_address',
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

// fix(#620): resource types with a frontend detail route the name can link to.
const RESOURCE_ROUTES: Record<string, string> = {
  dataset: '/datasets',
  map: '/maps',
  collection: '/collections',
};

// Canonical action strings currently emitted by audited application paths. Keep
// the exact stored values visible so operators can correlate filters with API
// responses and SIEM rules instead of relying on stale display-only aliases.
//
// fix(#1230): kept in sync by hand against the backend's authoritative
// registry (backend/app/modules/audit/actions.py, enforced there by
// test_audit_action_registry.py) — this array itself is not generated. The
// four `layer.*` entries removed here (layer.add, layer.remove,
// layer.reorder, layer.bulk_remove) were ghosts: builder layer edits write
// to map edit history, not audit_logs, so nothing ever emitted them.
const CURRENT_AUDIT_ACTIONS = [
  'api_key.create',
  'api_key.revoke',
  'attribute.edit',
  'attribute.reset',
  'audit.export',
  'collection.add_datasets',
  'collection.create',
  'collection.delete',
  'collection.remove_dataset',
  'collection.update',
  'config_export',
  'config_import',
  'connector.discover',
  'connector.ingest_dispatch',
  'dataset.create',
  'dataset.delete',
  'dataset.download_cog',
  'dataset.export',
  'dataset.view',
  'embed_token.bulk_revoke',
  'embed_token.create',
  'embed_token.revoke',
  'embed_token.update',
  'embedding.backfill',
  'feature.delete',
  'feature.insert',
  'feature.replace',
  'feature.update',
  'job.cancel',
  'job.cleanup_stale',
  'job.retry',
  'layer.add_column',
  'layer.alter_column_type',
  'layer.drop_column',
  'layer.rename_column',
  'map.admin_share_revoke',
  'map.add_layer',
  'map.bulk_remove_layers',
  'map.create',
  'map.delete',
  'map.duplicate',
  'map.import_style',
  'map.patch_layers',
  'map.remove_layer',
  'map.revoke_share',
  'map.share',
  'map.update',
  'map.update_share_token',
  'metadata.edit',
  'notification.test_sent',
  'oauth.login.failure',
  'oauth.login.init',
  'oauth.login.success',
  'oauth_provider.create',
  'oauth_provider.delete',
  'oauth_provider.update',
  'preview_service_layer',
  'probe_service',
  'query.execute',
  'query.reject',
  'refresh.abandoned',
  'refresh.cancelled',
  'refresh.dispatch',
  'refresh.failed',
  'refresh.succeeded',
  'reset',
  'reupload.commit',
  'stac_connect',
  'stac_import',
  'update',
  'user.approve',
  'user.change_password',
  'user.convert_saml_to_local',
  'user.create',
  'user.deactivate',
  'user.delete',
  'user.export',
  'user.login.failure',
  'user.login.success',
  'user.logout',
  'user.register',
  'user.reject',
  'user.update',
  'user.verify_email',
] as const;

export function AuditLogViewer() {
  const { t } = useTranslation('admin');
  // Sort lives in the URL so a sorted view is shareable. Sort clicks REPLACE
  // the history entry rather than pushing — deliberately, per the #1200
  // review: pushing would make five header clicks cost five Back presses to
  // leave the page, and it matches JobList's replace-on-refinement pattern
  // (#1185). The trade is that Back leaves the page instead of stepping
  // through orderings. An unrecognised ?sort= falls back to the default
  // rather than erroring the page; the API refuses it independently.
  const [searchParams, setSearchParams] = useSearchParams();
  const sortField = parseSortField(searchParams.get('sort'));
  const sortOrder = parseSortOrder(searchParams.get('order'));
  const [action, setAction] = useState('');
  const [userId, setUserId] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [resourceId, setResourceId] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const toggleRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function handleSort(field: string) {
    // Compare against the EFFECTIVE field, not the raw param: with no ?sort=
    // the Timestamp column already renders as the active descending sort, so
    // clicking it must flip to ascending rather than re-assert descending.
    const next = sortField === field && sortOrder === 'asc' ? 'desc' : 'asc';
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
  const normalizedUserId = userId.trim();
  const normalizedResourceId = resourceId.trim();
  const userIdInvalid = normalizedUserId !== '' && !UUID_PATTERN.test(normalizedUserId);
  const resourceIdInvalid = normalizedResourceId !== '' && !UUID_PATTERN.test(normalizedResourceId);
  const filtersValid = !userIdInvalid && !resourceIdInvalid;
  const userIdFilter = normalizedUserId || undefined;
  const resourceIdFilter = normalizedResourceId || undefined;

  const {
    data: queryData,
    isLoading: queryIsLoading,
    error: queryError,
    refetch,
  } = useAuditLogs({
    user_id: userIdFilter,
    action: action || undefined,
    resource_type: resourceType || undefined,
    resource_id: resourceIdFilter,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    search: searchQuery || undefined,
    skip,
    limit: PAGE_SIZE,
    sort: sortField,
    order: sortOrder,
  }, { enabled: filtersValid });
  // keepPreviousData must not leave a broad prior result visible beside an
  // invalid, visibly populated identity filter.
  const data = filtersValid ? queryData : undefined;
  const isLoading = filtersValid && queryIsLoading;
  const error = filtersValid ? queryError : null;

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
    setUserId('');
    setResourceType('');
    setResourceId('');
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
        <CardTitle level={2} className="text-sm font-medium">{t('audit.title')}</CardTitle>
        <CardAction className="flex items-center gap-2">
          <ExportSplitButton
            disabled={!filtersValid}
            filters={{
              user_id: userIdFilter,
              action: action || undefined,
              resource_type: resourceType || undefined,
              resource_id: resourceIdFilter,
              date_from: dateFrom || undefined,
              date_to: dateTo || undefined,
              search: searchQuery || undefined,
            }}
          />
          <DataTableSearch
            value={searchQuery}
            onChange={(v) => { setSearchQuery(v); setPage(0); }}
            placeholder={t('audit.searchPlaceholder')}
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <FilterSelect
            label={t('audit.filters.action')}
            value={action}
            onChange={(v) => { setAction(v); setPage(0); }}
            options={[
              { value: '', label: t('audit.filters.allActions') },
              ...CURRENT_AUDIT_ACTIONS.map((value) => ({ value, label: value })),
            ]}
          />
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.userId')}
            </label>
            <Input
              aria-label={t('audit.filters.userId')}
              aria-invalid={userIdInvalid}
              aria-describedby={userIdInvalid ? 'audit-user-id-error' : undefined}
              value={userId}
              onChange={(e) => { setUserId(e.target.value); setPage(0); }}
              placeholder={t('audit.filters.uuidPlaceholder')}
              className="h-8 w-52"
            />
            {userIdInvalid && (
              <p id="audit-user-id-error" className="mt-1 text-xs text-destructive">
                {t('audit.filters.invalidUuid')}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.resourceType')}
            </label>
            <Input
              aria-label={t('audit.filters.resourceType')}
              value={resourceType}
              onChange={(e) => { setResourceType(e.target.value); setPage(0); }}
              placeholder={t('audit.filters.resourceTypePlaceholder')}
              className="h-8 w-40"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.resourceId')}
            </label>
            <Input
              aria-label={t('audit.filters.resourceId')}
              aria-invalid={resourceIdInvalid}
              aria-describedby={resourceIdInvalid ? 'audit-resource-id-error' : undefined}
              value={resourceId}
              onChange={(e) => { setResourceId(e.target.value); setPage(0); }}
              placeholder={t('audit.filters.uuidPlaceholder')}
              className="h-8 w-52"
            />
            {resourceIdInvalid && (
              <p id="audit-resource-id-error" className="mt-1 text-xs text-destructive">
                {t('audit.filters.invalidUuid')}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              {t('audit.filters.from')}
            </label>
            <Input
              type="date"
              aria-label={t('audit.filters.from')}
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
              aria-label={t('audit.filters.to')}
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
          <ErrorState message={t('audit.errorLoading', { message: error.message })} onRetry={() => refetch()} />
        )}

        {/* Loading skeleton */}
        {isLoading && !data ? (
          <Table aria-label={t('audit.title')}>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <span className="sr-only">{t('audit.table.details', { defaultValue: 'Details' })}</span>
                </TableHead>
                <TableHead>{t('audit.table.timestamp')}</TableHead>
                <TableHead>{t('audit.table.user')}</TableHead>
                <TableHead>{t('audit.table.action')}</TableHead>
                <TableHead>{t('audit.table.resource')}</TableHead>
                <TableHead>{t('audit.table.resourceName')}</TableHead>
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
                { width: 'w-24' },
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
                <Table aria-label={t('audit.title')} containerFocusable={false}>
                <TableHeader>
                  <TableRow>
                    {/* The disclosure column has no data to order by. */}
                    <TableHead className="w-12">
                      <span className="sr-only">{t('audit.table.details', { defaultValue: 'Details' })}</span>
                    </TableHead>
                    <SortableColumnHeader
                      label={t('audit.table.timestamp')}
                      field="created_at"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('audit.table.user')}
                      field="username"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('audit.table.action')}
                      field="action"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    <SortableColumnHeader
                      label={t('audit.table.resource')}
                      field="resource_type"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
                    {/* Resource name and id are intentionally not sortable —
                        see SORTABLE_FIELDS. */}
                    <TableHead>{t('audit.table.resourceName')}</TableHead>
                    <TableHead>{t('audit.table.resourceId')}</TableHead>
                    <SortableColumnHeader
                      label={t('audit.table.ipAddress')}
                      field="ip_address"
                      activeField={sortField}
                      direction={sortOrder}
                      onSort={handleSort}
                    />
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
                              <ChevronRight className="size-4 rtl-mirror" />
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
                        <TableCell className="max-w-48 truncate">
                          {log.resource_name && log.resource_type && log.resource_id
                            && RESOURCE_ROUTES[log.resource_type] ? (
                              <Link
                                to={`${RESOURCE_ROUTES[log.resource_type]}/${log.resource_id}`}
                                className="text-primary hover:underline"
                                title={log.resource_name}
                              >
                                {log.resource_name}
                              </Link>
                            ) : (
                              <span title={log.resource_name ?? undefined}>
                                {log.resource_name ?? '-'}
                              </span>
                            )}
                        </TableCell>
                        <TableCell
                          className="font-mono text-xs"
                          title={log.resource_id ?? undefined}
                        >
                          {log.resource_id
                            ? log.resource_id.slice(0, 8) + '...'
                            : '-'}
                        </TableCell>
                        <TableCell>{log.ip_address ?? '-'}</TableCell>
                      </TableRow>
                      {expandedId === log.id && (
                        <TableRow>
                          <TableCell colSpan={8}>
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
