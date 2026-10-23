import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, Pencil, Plus, Trash, UserRoundCog, Users } from 'lucide-react';
import { useGroupList } from '@/hooks/use-admin-groups';
import { formatDate } from '@/lib/format';
import { paginationRange } from '@/lib/pagination';
import type { GroupResponse } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { DataTablePagination } from './DataTablePagination';
import { DataTableSkeleton } from './DataTableSkeleton';
import { GroupNameDialog } from './GroupNameDialog';
import { GroupDeleteDialog } from './GroupDeleteDialog';
import { GroupMembersDialog } from './GroupMembersDialog';

const PAGE_SIZE = 20;

export function GroupList() {
  const { t } = useTranslation('admin');
  const [page, setPage] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [renaming, setRenaming] = useState<GroupResponse | null>(null);
  const [deleting, setDeleting] = useState<GroupResponse | null>(null);
  const [managing, setManaging] = useState<GroupResponse | null>(null);

  const { data, isLoading, isFetching, isPlaceholderData, error, refetch } = useGroupList({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  // Deleting the last group on a page leaves that page empty. A placeholder
  // is the previous page's data, which would step back again before the
  // earlier page has loaded.
  useEffect(() => {
    if (page > 0 && data && !isPlaceholderData && data.groups.length === 0) setPage(page - 1);
  }, [page, data, isPlaceholderData]);

  if (error) {
    return <ErrorState message={t('groups.errorLoading', { message: error.message })} onRetry={() => refetch()} />;
  }

  const { totalPages, rangeStart, rangeEnd } = paginationRange(data?.total ?? 0, page, PAGE_SIZE);
  const isEmpty = !isLoading && data != null && data.groups.length === 0;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle level={2} className="flex items-center gap-2 text-sm font-medium">
            {t('groups.listHeading')}
            {data ? <Badge variant="secondary">{data.total}</Badge> : null}
          </CardTitle>
          <CardAction>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="me-2 h-4 w-4" /> {t('groups.create.button')}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Table aria-label={t('groups.title')}>
            <TableHeader>
              <TableRow>
                <TableHead>{t('groups.table.name')}</TableHead>
                <TableHead>{t('groups.table.members')}</TableHead>
                <TableHead className="hidden sm:table-cell">{t('groups.table.created')}</TableHead>
                <TableHead>{t('groups.table.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && !data ? (
                <DataTableSkeleton columns={[{ width: 'w-32' }, { width: 'w-10' }, { width: 'w-20' }, { width: 'w-24' }]} />
              ) : isEmpty ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <EmptyState
                      icon={Users}
                      title={t('groups.empty.title')}
                      description={t('groups.empty.hint')}
                      // keepPreviousData holds the old page while a new query loads.
                      announce={!isFetching}
                      className="border-0 py-12"
                      action={
                        <Button size="sm" onClick={() => setShowCreate(true)}>
                          <Plus className="me-2 h-4 w-4" /> {t('groups.create.button')}
                        </Button>
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : (
                (data?.groups ?? []).map((group) => (
                  <TableRow key={group.id}>
                    <TableCell className="whitespace-normal break-words font-medium sm:whitespace-nowrap">{group.name}</TableCell>
                    <TableCell>{t('groups.table.memberCount', { count: group.member_count })}</TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">{formatDate(group.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={t('groups.members.title', { name: group.name })}
                          onClick={() => setManaging(group)}
                        >
                          <UserRoundCog className="h-4 w-4 sm:me-2" aria-hidden="true" />
                          <span className="hidden sm:inline">{t('groups.table.manageMembers')}</span>
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" aria-label={t('groups.actionsFor', { name: group.name })}>
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setRenaming(group)}>
                              <Pencil className="me-2 h-4 w-4" /> {t('groups.rename.button')}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => setDeleting(group)} className="text-destructive">
                              <Trash className="me-2 h-4 w-4" /> {t('common:delete')}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
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

      {showCreate && <GroupNameDialog open onOpenChange={setShowCreate} />}
      {renaming && (
        <GroupNameDialog group={renaming} open onOpenChange={(open) => { if (!open) setRenaming(null); }} />
      )}
      {deleting && (
        <GroupDeleteDialog group={deleting} open onOpenChange={(open) => { if (!open) setDeleting(null); }} />
      )}
      {managing && (
        <GroupMembersDialog group={managing} open onOpenChange={(open) => { if (!open) setManaging(null); }} />
      )}
    </>
  );
}
