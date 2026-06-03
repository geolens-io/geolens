/**
 * Frontend mirror of the backend's canonical capability registry at
 * `backend/app/core/permissions.py:ALL_CAPABILITIES`.
 *
 * v13.14 Phase 281 surfaced a typo bug (`view_audit` was not in the registry,
 * so `can('view_audit')` returned false for admins and the audit page-guard
 * always redirected). The bug class is "weak typing on `can(capability: string)`
 * accepts any literal" — this module closes it: every `can()` call now must
 * pass a member of the `Capability` union, and TypeScript fails compile if
 * a typo or an unregistered key is passed.
 *
 * Drift contract: whenever a capability is added, removed, or renamed in the
 * backend `ALL_CAPABILITIES` list, this array must update in lockstep. The
 * test at `__tests__/capabilities.test.ts` polls `GET /auth/permissions/`
 * with each role's known mapping and would catch most drift; the static-
 * analysis test at `backend/tests/test_capability_drift.py` reads this file
 * directly and asserts byte-for-byte alignment with the backend list.
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
] as const;

export type Capability = (typeof ALL_CAPABILITIES)[number];
