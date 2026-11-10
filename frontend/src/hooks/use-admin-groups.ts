import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { queryKeys } from '@/lib/query-keys';
import { useModeAwareCapability } from '@/hooks/use-settings-admin';
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
  return useModeAwareCapability('manage_users');
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

type GroupToast = 'created' | 'renamed' | 'deleted';

// Mutation errors stay on the mutation so the open dialog can show the
// server's reason next to the field that caused it.
function useGroupMutation<V>(mutationFn: (variables: V) => Promise<unknown>, toastKey: GroupToast) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
      toast.success(i18n.t(`admin:groups.toasts.${toastKey}`));
    },
  });
}

export function useCreateGroup() {
  return useGroupMutation((name: string) => createGroup(name), 'created');
}

export function useRenameGroup() {
  return useGroupMutation(
    ({ groupId, name }: { groupId: string; name: string }) => renameGroup(groupId, name),
    'renamed',
  );
}

export function useDeleteGroup() {
  return useGroupMutation((groupId: string) => deleteGroup(groupId), 'deleted');
}

// Member lists nest under allGroups, so one invalidation also refreshes the
// member counts the list shows.
function invalidateMembership(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: queryKeys.admin.allGroups });
}

export function useAddGroupMember(groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => addGroupMembers(groupId, [userId]),
    onSuccess: () => invalidateMembership(qc),
  });
}

export function useRemoveGroupMember(groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => removeGroupMember(groupId, userId),
    onSuccess: () => invalidateMembership(qc),
  });
}
