import { apiFetch } from './client';
import type { GroupRef, GroupRefListResponse } from '@/types/api';

/** The groups the caller may share with: their own, or every group for an admin. */
export async function listMyGroups(): Promise<GroupRef[]> {
  const limit = 200;
  const groups: GroupRef[] = [];
  for (let skip = 0; ; skip += limit) {
    const page = await apiFetch<GroupRefListResponse>(`/groups/mine/?skip=${skip}&limit=${limit}`);
    groups.push(...page.groups);
    if (groups.length >= page.total || page.groups.length < limit) return groups;
  }
}
