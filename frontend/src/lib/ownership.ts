/**
 * Client-side owner-or-admin rule for catalog resources.
 *
 * Mirrors the backend guards (`check_dataset_write_access`,
 * `check_collection_ownership`, `check_map_ownership`): only the resource's
 * creator or a global admin may mutate it. This is a UI affordance, not a
 * security boundary — the backend is authoritative and will 403 regardless.
 * Keeping the front end in sync just avoids showing controls that would fail.
 */

/** A resource that records its creator's user id. */
export interface OwnedResource {
  created_by?: string | null;
}

/**
 * True if the current user may mutate the resource (its creator, or an admin).
 *
 * Resources with no recorded owner (`created_by` null — seeded/imported data,
 * or rows whose owner was deleted) are admin-only, matching the backend.
 */
export function canMutateResource(
  resource: OwnedResource | null | undefined,
  currentUserId: string | null | undefined,
  isAdmin: boolean,
): boolean {
  if (isAdmin) return true;
  if (!resource?.created_by || !currentUserId) return false;
  return resource.created_by === currentUserId;
}
