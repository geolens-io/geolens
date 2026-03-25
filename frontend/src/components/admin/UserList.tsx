import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useUserList,
  useApproveUser,
  useRejectUser,
  useDeactivateUser,
} from '@/hooks/use-admin';
import { formatDate } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import { userStatusColors, activeDotColor } from '@/lib/status-colors';
import type { UserResponse } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
  MoreHorizontal,
  UserPlus,
  Check,
  X,
  Edit,
  UserX,
  Trash,
} from 'lucide-react';
import { UserCreateDialog } from './UserCreateDialog';
import { UserEditDialog } from './UserEditDialog';
import { UserDeleteDialog } from './UserDeleteDialog';
import { DataTablePagination } from './DataTablePagination';
import { DataTableSearch } from './DataTableSearch';
import { DataTableSkeleton } from './DataTableSkeleton';
import { FilterSelect } from './FilterSelect';
import { RoleSelect } from './RoleSelect';
import { ErrorState } from '@/components/layout/ErrorState';

const PAGE_SIZE = 20;

const STATUS_OPTIONS = [
  { value: '', labelKey: 'users.filters.allUsers' },
  { value: 'pending', labelKey: 'users.filters.pending' },
  { value: 'active', labelKey: 'users.filters.active' },
];

export function UserList() {
  const { t } = useTranslation('admin');
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

  const skip = page * PAGE_SIZE;
  const { data, isLoading, error } = useUserList(skip, PAGE_SIZE, statusFilter || undefined, searchQuery || undefined);

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

  if (error) {
    return <ErrorState message={t('users.errorLoading', { message: error.message })} />;
  }

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">
              {data ? t('users.titleCount', { count: data.total }) : t('users.title')}
            </CardTitle>
            <div className="flex items-center gap-3">
              <DataTableSearch
                value={searchQuery}
                onChange={(v) => { setSearchQuery(v); setPage(0); }}
                placeholder={t('users.table.username') + ' / ' + t('users.table.email')}
              />
              <FilterSelect
                label=""
                value={statusFilter}
                onChange={(v) => { setStatusFilter(v); setPage(0); }}
                options={STATUS_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey) }))}
              />
              <Button size="sm" onClick={() => setShowCreateDialog(true)}>
                <UserPlus className="mr-2 h-4 w-4" /> {t('users.addUser')}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('users.table.username')}</TableHead>
                <TableHead>{t('users.table.email')}</TableHead>
                <TableHead>{t('users.table.roles')}</TableHead>
                <TableHead>{t('users.table.status')}</TableHead>
                <TableHead>{t('users.table.active')}</TableHead>
                <TableHead>{t('users.table.created')}</TableHead>
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
                  { width: 'w-2.5', rounded: true },
                  { width: 'w-20' },
                  { width: 'w-8' },
                ]} />
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
                      <Badge variant="outline" className={userStatusColors[user.status] ?? 'bg-muted text-muted-foreground border-border'}>
                        {user.status === 'pending' ? t('users.status.pending') : t('users.status.active')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`inline-block h-2.5 w-2.5 rounded-full ${
                          activeDotColor[String(user.is_active) as keyof typeof activeDotColor]
                        }`}
                        title={user.is_active ? t('users.status.active') : t('users.status.inactive')}
                      />
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
                                <Check className="mr-2 h-4 w-4" /> {t('users.actions.approve')}
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleReject(user)} className="text-destructive">
                                <X className="mr-2 h-4 w-4" /> {t('users.actions.reject')}
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                            </>
                          )}
                          <DropdownMenuItem onClick={() => setEditingUser(user)}>
                            <Edit className="mr-2 h-4 w-4" /> {t('common:edit')}
                          </DropdownMenuItem>
                          {user.is_active ? (
                            <DropdownMenuItem onClick={() => handleDeactivate(user)} className="text-destructive">
                              <UserX className="mr-2 h-4 w-4" /> {t('users.actions.deactivate')}
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuItem onClick={() => setDeletingUser(user)} className="text-destructive">
                            <Trash className="mr-2 h-4 w-4" /> {t('common:delete')}
                          </DropdownMenuItem>
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
    </>
  );
}
