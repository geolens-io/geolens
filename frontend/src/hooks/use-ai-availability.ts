import { useQuery } from '@tanstack/react-query';
import { useAIStatus } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';
import { getAIAvailability } from '@/api/maps';
import { queryKeys } from '@/lib/query-keys';

/**
 * Resolves whether the caller can use builder AI chat, combining AI readiness
 * with the caller's `use_ai_chat` capability.
 *
 * ## Two readiness sources (builder-audit #338 P1-11)
 *
 * - **Admins** read the detailed `/api/admin/ai-status/` endpoint (provider, key
 *   presence) so the disabled-state UI can distinguish `env_disabled` vs `no_key`.
 * - **Non-admin editors holding `use_ai_chat`** read the public-safe
 *   `/api/ai/availability/` endpoint, which returns only a boolean and leaks no
 *   provider/key detail. This lets a permitted editor open builder chat when AI
 *   is enabled and configured — previously the hook returned `false` for every
 *   non-admin because only admins could read the admin status endpoint.
 * - **Viewers (no `use_ai_chat`)** fire NEITHER endpoint, so there is no 401/403
 *   console noise; they get a safe disabled state with `reason = 'permission'`.
 *
 * Both endpoints are gated on `!!token` so anonymous sessions never probe them
 * (CONSOLE-01 / Phase 1054).
 *
 * ## reason field (Phase 1135 AI-02 — BuilderRail disabled-state UI)
 *
 * The `reason` field gives the disabled-state UI (UI-SPEC Surface 3) a
 * per-cause taxonomy without re-deriving the gate logic from raw query data.
 *
 * Precedence (first match wins):
 *   1. `permission`    — caller lacks `use_ai_chat` (no endpoint was queried)
 *   2. `env_disabled`  — admin only: AI_ENABLED=false at the instance level
 *   3. `no_key`        — AI enabled but no provider API key configured (admin
 *                        distinguishes this; non-admins see it for any
 *                        not-available signal, since the public endpoint
 *                        intentionally collapses env_disabled/no_key)
 *   4. `null`          — either `isAIAvailable === true` (AI fully available)
 *                        OR still loading (UI shows a spinner via `isLoading`)
 *
 * The loading state intentionally maps to `null`, not a reason constant, because
 * the disabled-state UI distinguishes "loading" from "unavailable" via `isLoading`,
 * and there is no actionable reason to surface while waiting for the API response.
 */
export type AIUnavailableReason = 'env_disabled' | 'no_key' | 'permission';

export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const { can } = usePermissions();
  const canUse = can('use_ai_chat');

  // Admins read the detailed admin status (provider/key info for the reason taxonomy).
  const adminStatus = useAIStatus({ enabled: !!token && isAdmin });
  // Non-admin editors holding use_ai_chat read the public-safe availability signal.
  // Viewers (!canUse) fire nothing — avoids 403 console noise.
  const availabilityQuery = useQuery({
    queryKey: queryKeys.maps.aiAvailability,
    queryFn: getAIAvailability,
    enabled: !!token && !isAdmin && canUse,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  const adminData = adminStatus.data;

  let isAIAvailable: boolean;
  let reason: AIUnavailableReason | null = null;

  if (!canUse) {
    isAIAvailable = false;
    reason = 'permission';
  } else if (isAdmin) {
    isAIAvailable = Boolean(adminData?.enabled && adminData?.configured);
    if (!isAIAvailable && adminData !== undefined) {
      reason = !adminData.enabled ? 'env_disabled' : 'no_key';
    }
  } else {
    isAIAvailable = Boolean(availabilityQuery.data?.available);
    // The public endpoint collapses env_disabled/no_key into a single boolean;
    // surface the more common "not configured" cause to non-admins (who cannot
    // act on either, and never see the admin Settings CTA).
    if (!isAIAvailable && availabilityQuery.data !== undefined) {
      reason = 'no_key';
    }
  }

  // Surface the loading/error state of whichever query is actually active so the
  // disabled-state UI can show a spinner instead of premature "unavailable" copy.
  const activeQuery = isAdmin ? adminStatus : availabilityQuery;
  const isLoading = canUse && activeQuery.fetchStatus !== 'idle' && activeQuery.isLoading;

  return {
    ...activeQuery,
    isLoading,
    isAIAvailable,
    reason,
  };
}
