import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  useUserList,
  useApproveUser,
  useRejectUser,
  useDeactivateUser,
} from '@/hooks/use-admin';
import { exportUsersCsv } from '@/api/admin';
import { triggerDownload, datedFilename } from '@/lib/download';
import { formatDate, formatBytes } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { userStatusColors } from '@/lib/status-colors';
import type { UserResponse } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Download,
  Loader2,
  MoreHorizontal,
  UserPlus,
  Check,
  X,
  Edit,
  UserX,
  KeyRound,
  Trash,
  Users,
} from 'lucide-react';
import { UserCreateDialog } from './UserCreateDialog';
import { UserEditDialog } from './UserEditDialog';
import { UserDeleteDialog } from './UserDeleteDialog';
import { UserResetPasswordDialog } from './UserResetPasswordDialog';
import { DataTablePagination } from './DataTablePagination';
import { SortableColumnHeader, type SortDirection } from './SortableColumnHeader';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { FilterSelect } from './FilterSelect';
import { RoleSelect } from './RoleSelect';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { useAuthStore } from '@/stores/auth-store';

const PAGE_SIZE = 20;

/** Mirrors the UserSortField allowlist on GET /admin/users/. Roles and storage
 *  are absent by design: roles is a many-to-many and storage is aggregated per
 *  page after the query, so neither can be ordered by the database. Offering a
 *  header for them would sort only the visible page, which looks correct and
 *  is not. */
const SORTABLE_FIELDS = ['username', 'email', 'status', 'last_login_at', 'created_at'] as const;
type SortField = (typeof SORTABLE_FIELDS)[number];

const DEFAULT_SORT: SortField = 'created_at';
const DEFAULT_ORDER: SortDirection = 'asc';

function parseSortField(raw: string | null): SortField {
  return SORTABLE_FIELDS.includes(raw as SortField) ? (raw as SortField) : DEFAULT_SORT;
}

function parseSortOrder(raw: string | null): SortDirection {
  return raw === 'desc' || raw === 'asc' ? raw : DEFAULT_ORDER;
}

const STATUS_OPTIONS = [
  { value: '', labelKey: 'users.filters.allUsers' },
  { value: 'pending', labelKey: 'users.filters.pending' },
  { value: 'active', labelKey: 'users.filters.active' },
  { value: 'suspended', labelKey: 'users.filters.suspended' },
  { value: 'deactivated', labelKey: 'users.filters.deactivated' },
];

export function UserList() {
  const { t } = useTranslation('admin');
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // Dialog states
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [editingUser, setEditingUser] = useState<UserResponse | null>(null);
  const [deletingUser, setDeletingUser] = useState<UserResponse | null>(null);
  const [approvingUser, setApprovingUser] = useState<UserResponse | null>(null);
  const [approveRole, setApproveRole] = useState('viewer');
  const [rejectingUser, setRejectingUser] = useState<UserResponse | null>(null);
  const [deactivatingUser, setDeactivatingUser] = useState<UserResponse | null>(null);
  const [resettingPasswordUser, setResettingPasswordUser] = useState<UserResponse | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  // Sort lives in the URL so a sorted view is shareable. Sort clicks REPLACE
  // the history entry rather than pushing — deliberately, per #1200 review:
  // pushing would make five header clicks cost five Back presses to leave the
  // page, and it matches JobList's replace-on-refinement pattern (#1185). The
  // trade is that Back leaves the page instead of stepping through orderings.
  // An unrecognised ?sort= falls back to the default rather than erroring the
  // page; the API refuses it independently.
  const [searchParams, setSearchParams] = useSearchParams();
  const sortField = parseSortField(searchParams.get('sort'));
  const sortOrder = parseSortOrder(searchParams.get('order'));

  function handleSort(field: string) {
    // Compare against the EFFECTIVE field, not the raw param: with no ?sort=
    // the Created column already renders as the active ascending sort, so
    // clicking it must flip to descending rather than re-assert ascending.
    const next = sortField === field && sortOrder === 'asc' ? 'desc' : 'asc';
    const params = new URLSearchParams(searchParams);
    params.set('sort', field);
    params.set('order', next);
    setSearchParams(params, { replace: true });
    // A new ordering renumbers every page, so page 3 of the old sort is
    // meaningless under the new one.
    setPage(0);
  }

  const skip = page * PAGE_SIZE;
  const { data, isLoading, error, refetch } = useUserList({
    skip,
    limit: PAGE_SIZE,
    status: statusFilter || undefined,
    search: searchQuery || undefined,
    sort: sortField,
    order: sortOrder,
  });

  const approveUser = useApproveUser();
  const rejectUser = useRejectUser();
  const deactivateUser = useDeactivateUser();

  function handleApprove(user: UserResponse) {
    setApprovingUser(user);
    setApproveRole('viewer');
  }

  function handleReject(user: UserResponse) {
    setRejectingUser(user);
  }

  function handleDeactivate(user: UserResponse) {
    setDeactivatingUser(user);
  }

  async function confirmApprove() {
    if (!approvingUser) return;
    try {
      await approveUser.mutateAsync({ userId: approvingUser.id, role: approveRole });
      setApprovingUser(null);
    } catch {
      // error stays visible via mutation state
    }
  }

  async function confirmReject() {
    if (!rejectingUser) return;
    try {
      await rejectUser.mutateAsync(rejectingUser.id);
      setRejectingUser(null);
    } catch {
      // error stays visible via mutation state
    }
  }

  async function confirmDeactivate() {
    if (!deactivatingUser) return;
    try {
      await deactivateUser.mutateAsync(deactivatingUser.id);
      setDeactivatingUser(null);
    } catch {
      // error stays visible via mutation state
    }
  }

  // fix(#438): UX-01 — was `window.open('/api/admin/users/export.csv')`, which
  // carries no Authorization header and so returned a 401 JSON body in a new tab.
  async function handleExportCsv() {
    setIsExporting(true);
    try {
      const blob = await exportUsersCsv();
      triggerDownload(blob, datedFilename('geolens-users', 'csv'));
    } catch {
      toast.error(t('users.exportError'));
    } finally {
      setIsExporting(false);
    }
  }

  if (error) {
    return <ErrorState message={t('users.errorLoading', { message: error.message })} onRetry={() => refetch()} />;
  }

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);
  const hasFilters = statusFilter !== '' || searchQuery !== '';
  const isEmpty = !isLoading && data != null && data.users.length === 0;

  return (
    <>
      <Card>
        <CardHeader className="has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
          <CardTitle
            level={2}
            aria-label={t('users.title')}
            className="flex items-center gap-2 text-sm font-medium"
          >
            {t('users.title')}
            {data ? <Badge variant="secondary">{data.total}</Badge> : null}
          </CardTitle>
          <CardAction className="col-start-1 row-start-2 row-span-1 flex w-full flex-wrap items-center gap-2 justify-self-stretch md:col-start-2 md:row-start-1 md:row-span-2 md:w-auto md:justify-self-end">
            <DataTableSearch
              value={searchQuery}
              onChange={(v) => { setSearchQuery(v); setPage(0); }}
              placeholder={t('users.searchPlaceholder')}
            />
            <FilterSelect
              label=""
              ariaLabel={t('users.table.status')}
              value={statusFilter}
              onChange={(v) => { setStatusFilter(v); setPage(0); }}
              options={STATUS_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey) }))}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleExportCsv}
              disabled={isExporting}
              aria-busy={isExporting || undefined}
            >
              {isExporting ? (
                <Loader2 className="me-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="me-2 h-4 w-4" />
              )}
              {t('users.exportEmailsCsv')}
            </Button>
            <Button size="sm" onClick={() => setShowCreateDialog(true)}>
              <UserPlus className="me-2 h-4 w-4" /> {t('users.addUser')}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Table aria-label={t('users.title')}>
            <TableHeader>
              <TableRow>
                <SortableColumnHeader
                  label={t('users.table.username')}
                  field="username"
                  activeField={sortField}
                  direction={sortOrder}
                  onSort={handleSort}
                />
                <SortableColumnHeader
                  label={t('users.table.email')}
                  field="email"
                  activeField={sortField}
                  direction={sortOrder}
                  onSort={handleSort}
                />
                {/* Roles and storage are intentionally not sortable — see
                    SORTABLE_FIELDS. */}
                <TableHead>{t('users.table.roles')}</TableHead>
                <SortableColumnHeader
                  label={t('users.table.status')}
                  field="status"
                  activeField={sortField}
                  direction={sortOrder}
                  onSort={handleSort}
                />
                <TableHead>{t('users.table.storage')}</TableHead>
                <SortableColumnHeader
                  label={t('users.table.lastLogin')}
                  field="last_login_at"
                  activeField={sortField}
                  direction={sortOrder}
                  onSort={handleSort}
                />
                <SortableColumnHeader
                  label={t('users.table.created')}
                  field="created_at"
                  activeField={sortField}
                  direction={sortOrder}
                  onSort={handleSort}
                />
                <TableHead>{t('users.table.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && !data ? (
                <DataTableSkeleton columns={[
                  { width: 'w-24' },
                  { width: 'w-32' },
                  { width: 'w-14', rounded: true },
                  { width: 'w-16', rounded: true },
                  { width: 'w-20' },
                  { width: 'w-20' },
                  { width: 'w-20' },
                  { width: 'w-8' },
                ]} />
              ) : isEmpty ? (
                /* fix(#438): UX-05 — filtering to zero used to render an empty
                   table body, which reads as a broken page. Siblings (JobList,
                   AuditLog, SharedMaps) all say something here. */
                <TableRow>
                  <TableCell colSpan={8}>
                    <EmptyState
                      icon={Users}
                      title={hasFilters ? t('users.empty.noResults') : t('users.empty.noUsers')}
                      description={hasFilters ? t('users.empty.noResultsHint') : undefined}
                      className="border-0 py-12"
                      action={
                        hasFilters ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setSearchQuery('');
                              setStatusFilter('');
                              setPage(0);
                            }}
                          >
                            {t('users.empty.clearFilters')}
                          </Button>
                        ) : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : (
                (data?.users ?? []).map((user) => (
                  <TableRow
                    key={user.id}
                    className={!user.is_active ? 'text-muted-foreground' : ''}
                  >
                    <TableCell className="font-medium">{user.username}</TableCell>
                    <TableCell>{user.email ?? '-'}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {user.roles.map((role) => (
                          <Badge key={role} variant="secondary" className="text-xs">
                            {role}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      {(() => {
                        const colorKey = user.status;
                        const label = t(`users.status.${user.status}`);
                        return (
                          <Badge variant="outline" className={userStatusColors[colorKey]}>
                            {label}
                          </Badge>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {user.quota_usage == null ? '—' : (
                        <>
                          {formatBytes(user.quota_usage.bytes_used)}
                          {' / '}
                          {user.quota_usage.storage_cap === 0
                            ? 'unlimited'
                            : formatBytes(user.quota_usage.storage_cap)}
                        </>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.last_login_at ? formatDate(user.last_login_at) : '—'}
                    </TableCell>
                    <TableCell>{formatDate(user.created_at)}</TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="sm" aria-label={t('users.actionsFor', { name: user.username })}>
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {user.status === 'pending' && (
                            <>
                              <DropdownMenuItem onClick={() => handleApprove(user)}>
                                <Check className="me-2 h-4 w-4" /> {t('users.actions.approve')}
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleReject(user)} className="text-destructive">
                                <X className="me-2 h-4 w-4" /> {t('users.actions.reject')}
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                            </>
                          )}
                          <DropdownMenuItem onClick={() => setEditingUser(user)}>
                            <Edit className="me-2 h-4 w-4" /> {t('common:edit')}
                          </DropdownMenuItem>
                          {/* feat(#1715): offered on every row, self included — an
                              admin who is still signed in but has forgotten their
                              password has no other way back, and change-password
                              needs the old value. The dialog says what a self-reset
                              costs. Accounts that sign in through an identity
                              provider are refused by the API with the reason. */}
                          <DropdownMenuItem onClick={() => setResettingPasswordUser(user)}>
                            <KeyRound className="me-2 h-4 w-4" /> {t('users.actions.resetPassword')}
                          </DropdownMenuItem>
                          {user.is_active && user.id !== currentUserId ? (
                            <DropdownMenuItem onClick={() => handleDeactivate(user)} className="text-destructive">
                              <UserX className="me-2 h-4 w-4" /> {t('users.actions.deactivate')}
                            </DropdownMenuItem>
                          ) : null}
                          {user.id !== currentUserId && (
                            <DropdownMenuItem onClick={() => setDeletingUser(user)} className="text-destructive">
                              <Trash className="me-2 h-4 w-4" /> {t('common:delete')}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <DataTablePagination
            page={page}
            totalPages={totalPages}
            rangeStart={rangeStart}
            rangeEnd={rangeEnd}
            total={data?.total ?? 0}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>

      {/* Approve Dialog */}
      <Dialog open={!!approvingUser} onOpenChange={(open) => { if (!open) setApprovingUser(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('users.approveDialog.title', { username: approvingUser?.username })}</DialogTitle>
            <DialogDescription>
              {t('users.approveDialog.description')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-sm font-medium">{t('users.approveDialog.roleLabel')}</label>
            <RoleSelect value={approveRole} onChange={setApproveRole} />
          </div>
          {approveUser.error && (
            <p className="text-sm text-destructive">
              {approveUser.error instanceof Error ? approveUser.error.message : t('users.approveDialog.error')}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setApprovingUser(null)}>{t('common:cancel')}</Button>
            <Button onClick={confirmApprove} disabled={approveUser.isPending}>
              {approveUser.isPending ? t('users.approveDialog.approving') : t('users.approveDialog.approve')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject Dialog */}
      <AlertDialog open={!!rejectingUser} onOpenChange={(open) => { if (!open) setRejectingUser(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('users.rejectDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('users.rejectDialog.description', { username: rejectingUser?.username })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {rejectUser.error && (
            <p className="text-sm text-destructive">
              {rejectUser.error instanceof Error ? rejectUser.error.message : t('users.rejectDialog.error')}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmReject}
              disabled={rejectUser.isPending}
              variant="destructive"
            >
              {rejectUser.isPending ? t('users.rejectDialog.rejecting') : t('users.rejectDialog.reject')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Deactivate Dialog */}
      <AlertDialog open={!!deactivatingUser} onOpenChange={(open) => { if (!open) setDeactivatingUser(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('users.deactivateDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('users.deactivateDialog.description', { username: deactivatingUser?.username })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deactivateUser.error && (
            <p className="text-sm text-destructive">
              {deactivateUser.error instanceof Error ? deactivateUser.error.message : t('users.deactivateDialog.error')}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeactivate}
              disabled={deactivateUser.isPending}
              variant="destructive"
            >
              {deactivateUser.isPending ? t('users.deactivateDialog.deactivating') : t('users.deactivateDialog.deactivate')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* CRUD Dialogs */}
      {showCreateDialog && (
        <UserCreateDialog open onOpenChange={setShowCreateDialog} />
      )}
      {editingUser && (
        <UserEditDialog
          user={editingUser}
          open
          onOpenChange={(open) => { if (!open) setEditingUser(null); }}
        />
      )}
      {deletingUser && (
        <UserDeleteDialog
          user={deletingUser}
          open
          onOpenChange={(open) => { if (!open) setDeletingUser(null); }}
        />
      )}
      {resettingPasswordUser && (
        <UserResetPasswordDialog
          user={resettingPasswordUser}
          open
          onOpenChange={(open) => { if (!open) setResettingPasswordUser(null); }}
        />
      )}
    </>
  );
}
