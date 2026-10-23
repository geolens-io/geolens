import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { queryKeys } from '@/lib/query-keys';
import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';
import {
  listGroups,
  createGroup,
  renameGroup,
  deleteGroup,
  listGroupMembers,
  addGroupMembers,
  removeGroupMember,
} from '@/api/admin';

// Mirrors require_group_admin in backend/app/modules/admin/router_groups.py:
// manage_users in single-tenant deployments, manage_tenants in multi-tenant.
export function useGroupAdmin(): boolean {
  const { can } = usePermissions();
  const { isMultiTenant, isResolved } = useEdition();
  if (!isResolved) return false;
  return isMultiTenant ? can('manage_tenants') : can('manage_users');
}

export function useGroupList(params: { skip: number; limit: number }) {
  const { skip, limit } = params;
  return useQuery({
    queryKey: queryKeys.admin.groups(skip, limit),
    queryFn: () => listGroups({ skip, limit }),
    placeholderData: keepPreviousData,
  });
}

export function useGroupMembers(groupId: string) {
  return useQuery({
    queryKey: queryKeys.admin.groupMembers(groupId),
    queryFn: () => listGroupMembers(groupId),
  });
}

// Mutation errors stay on the mutation so the open dialog can show the
// server's reason next to the field that caused it.
export function useCreateGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createGroup(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
      toast.success(i18n.t('admin:groups.toasts.created'));
    },
  });
}

export function useRenameGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, name }: { groupId: string; name: string }) => renameGroup(groupId, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
      toast.success(i18n.t('admin:groups.toasts.renamed'));
    },
  });
}

export function useDeleteGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => deleteGroup(groupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
      toast.success(i18n.t('admin:groups.toasts.deleted'));
    },
  });
}

function invalidateMembership(qc: ReturnType<typeof useQueryClient>, groupId: string) {
  qc.invalidateQueries({ queryKey: queryKeys.admin.groupMembers(groupId) });
  // The list shows each group's member count.
  qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
}

export function useAddGroupMember(groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => addGroupMembers(groupId, [userId]),
    onSuccess: () => invalidateMembership(qc, groupId),
  });
}

export function useRemoveGroupMember(groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => removeGroupMember(groupId, userId),
    onSuccess: () => invalidateMembership(qc, groupId),
  });
}
