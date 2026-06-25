import { describe, it, expect } from 'vitest';
import { canMutateResource } from '@/lib/ownership';

describe('canMutateResource', () => {
  const me = 'user-1';
  const other = 'user-2';

  it('allows the owner', () => {
    expect(canMutateResource({ created_by: me }, me, false)).toBe(true);
  });

  it('denies a non-owner non-admin', () => {
    expect(canMutateResource({ created_by: other }, me, false)).toBe(false);
  });

  it('allows an admin regardless of owner', () => {
    expect(canMutateResource({ created_by: other }, me, true)).toBe(true);
  });

  it('treats a null/unowned resource as admin-only', () => {
    expect(canMutateResource({ created_by: null }, me, false)).toBe(false);
    expect(canMutateResource({ created_by: null }, me, true)).toBe(true);
  });

  it('denies when there is no current user (anonymous), unless admin flag set', () => {
    expect(canMutateResource({ created_by: me }, null, false)).toBe(false);
    expect(canMutateResource(undefined, null, false)).toBe(false);
  });
});
