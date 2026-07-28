import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';

// fix(#653): mirror the backend's require_ai_status_reader
// (backend/app/modules/admin/router.py), which gates /admin/ai-status on
// manage_users in single-tenant deployments but manage_tenants in
// multi-tenant. Every frontend surface that reads AI status must gate on
// this hook so the pattern can't drift per-component again (it was first
// inlined for #652, then missed twice).
//
// Scope note: this covers /admin/ai-status ONLY. /admin/embedding-stats and
// /admin/backfill-embeddings require manage_users in BOTH modes — do not
// swap their gates to this hook.
export function useAIStatusReader(): boolean {
  const { can } = usePermissions();
  const { isMultiTenant } = useEdition();
  return isMultiTenant ? can('manage_tenants') : can('manage_users');
}
