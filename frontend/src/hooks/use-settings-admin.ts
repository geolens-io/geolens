import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';
import type { Capability } from '@/lib/capabilities';

// Mirrors the backend's require_settings_admin
// (backend/app/modules/settings/router.py) and require_config_operator
// (backend/app/platform/config_ops/router.py), which gate /settings/* and
// /config-ops/* on manage_settings in single-tenant deployments but
// manage_tenants in multi-tenant. A per-tenant admin holds manage_settings
// without manage_tenants, so every surface that routes or links to
// /admin/settings/* or /admin/config-ops must gate on this hook (as
// useAIStatusReader does for /admin/ai-status reads).
export function useSettingsAdmin(): boolean {
  return useModeAwareCapability('manage_settings');
}

/** `single` in single-tenant deployments, manage_tenants in multi-tenant ones. */
export function useModeAwareCapability(single: Capability): boolean {
  const { can } = usePermissions();
  const { isMultiTenant, isResolved } = useEdition();
  // Fail closed until the tenancy mode is known: assuming single-tenant while
  // the edition query is pending or failed would briefly authorize a
  // multi-tenant per-tenant admin into pages where every read and save 403s.
  if (!isResolved) return false;
  return isMultiTenant ? can('manage_tenants') : can(single);
}
