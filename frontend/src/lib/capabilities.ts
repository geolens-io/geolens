/**
 * Frontend mirror of the backend's canonical capability registry at
 * `backend/app/core/permissions.py:ALL_CAPABILITIES`.
 *
 * Every `can()` call must pass a member of the `Capability` union, so a typo or
 * an unregistered key fails to compile instead of silently returning false.
 *
 * Drift contract: `backend/tests/test_capability_drift.py` reads this file
 * directly and asserts byte-for-byte alignment with the backend list;
 * `__tests__/capabilities.test.ts` also polls `GET /auth/permissions/` against
 * each role's known mapping.
 *
 * @public Read as text by that test, so it stays exported.
 */
export const ALL_CAPABILITIES = [
  'upload',
  'create_layers',
  'export',
  'edit_metadata',
  'manage_collections',
  'use_ai_chat',
  'manage_users',
  'manage_settings',
  'manage_tenants',
] as const;

export type Capability = (typeof ALL_CAPABILITIES)[number];
