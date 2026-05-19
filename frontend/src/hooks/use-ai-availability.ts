import { useAIStatus } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';

/**
 * Combines admin AI status with the caller's `use_ai_chat` capability.
 *
 * Gated on `!!token && isAdmin` (CONSOLE-01 / Phase 1054):
 * `/api/admin/ai-status/` requires admin; firing it for anonymous
 * or non-admin authed sessions surfaces 401/403 in the browser console
 * for every dataset-detail tab (OverviewTab, MetadataTab, SourceQualityTab,
 * MapCreateDialog). Mirrors the `AIStatusCard` / `SettingsAITab` pattern.
 *
 * Non-admin users see `isAIAvailable = false` because the underlying
 * `aiStatus.data` will never load — which is the correct UX: only admins
 * configure AI, only admins know whether it's wired up.
 */
export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const aiStatus = useAIStatus({ enabled: !!token && isAdmin });
  const { can } = usePermissions();

  return {
    ...aiStatus,
    isAIAvailable: Boolean(
      aiStatus.data?.enabled && aiStatus.data?.configured && can('use_ai_chat'),
    ),
  };
}
