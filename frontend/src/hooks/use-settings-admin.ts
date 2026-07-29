import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';

// fix(#817): mirror the backend's require_settings_admin
// (backend/app/modules/settings/router.py) and require_config_operator
// (backend/app/platform/config_ops/router.py), which gate every /settings/*
// and /config-ops/* endpoint on manage_settings in single-tenant deployments
// but manage_tenants in multi-tenant. A default per-tenant admin holds
// manage_settings without manage_tenants, so a plain manage_settings gate
// admitted them to the Settings tabs where every read and save 403s. Every
// surface that routes or links to /admin/settings/* or /admin/config-ops
// must gate on this hook so the pattern can't drift per-component (same
// pattern as useAIStatusReader for /admin/ai-status reads, #653).
export function useSettingsAdmin(): boolean {
  const { can } = usePermissions();
  const { isMultiTenant } = useEdition();
  return isMultiTenant ? can('manage_tenants') : can('manage_settings');
}
