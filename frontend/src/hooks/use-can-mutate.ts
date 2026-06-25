import { useAuthStore } from '@/stores/auth-store';
import { canMutateResource, type OwnedResource } from '@/lib/ownership';

/**
 * True if the current user may mutate the given resource — its creator, or an
 * admin. Gate edit/delete/publish/share controls on this rather than role
 * alone, so the UI matches the backend owner-or-admin guards. See
 * `lib/ownership.ts`.
 */
export function useCanMutate(resource: OwnedResource | null | undefined): boolean {
  const currentUserId = useAuthStore((s) => s.user?.id ?? null);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  return canMutateResource(resource, currentUserId, isAdmin);
}
