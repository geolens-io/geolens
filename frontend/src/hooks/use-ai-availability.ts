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
 *
 * ## reason field (Phase 1135 AI-02 — BuilderRail disabled-state UI)
 *
 * The `reason` field gives the disabled-state UI (UI-SPEC Surface 3) a
 * per-cause taxonomy without re-deriving the gate logic from raw query data.
 *
 * Precedence (first match wins):
 *   1. `env_disabled`  — admin has set AI_ENABLED=false at the instance level
 *   2. `no_key`        — AI enabled at env level but no provider API key configured
 *   3. `permission`    — status loaded, key configured, but caller lacks `use_ai_chat`
 *   4. `null`          — either `isAIAvailable === true` (AI fully available)
 *                        OR `aiStatus.isLoading === true` (still fetching; UI shows spinner)
 *
 * The loading state intentionally maps to `null`, not a reason constant, because
 * the disabled-state UI distinguishes "loading" from "unavailable" via `isLoading`,
 * and there is no actionable reason to surface while waiting for the API response.
 */
export type AIUnavailableReason = 'env_disabled' | 'no_key' | 'permission';

export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const aiStatus = useAIStatus({ enabled: !!token && isAdmin });
  const { can } = usePermissions();

  const status = aiStatus.data;
  const canUse = can('use_ai_chat');
  const isAIAvailable = Boolean(status?.enabled && status?.configured && canUse);

  let reason: AIUnavailableReason | null = null;
  if (!isAIAvailable && status !== undefined) {
    if (!status.enabled) {
      reason = 'env_disabled';
    } else if (!status.configured) {
      reason = 'no_key';
    } else if (!canUse) {
      reason = 'permission';
    }
  }

  return {
    ...aiStatus,
    isAIAvailable,
    reason,
  };
}
