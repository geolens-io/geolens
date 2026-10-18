import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';

// Mirrors the backend's require_ai_status_reader, which gates /admin/ai-status
// on manage_users in single-tenant deployments and manage_tenants in
// multi-tenant. Covers /admin/ai-status ONLY: /admin/embedding-stats and
// /admin/backfill-embeddings require manage_users in both modes.
export function useAIStatusReader(): boolean {
  const { can } = usePermissions();
  const { isMultiTenant } = useEdition();
  return isMultiTenant ? can('manage_tenants') : can('manage_users');
}
