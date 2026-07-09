import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { formatMutationError } from '@/lib/error-map';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import {
  getBasemaps,
  getMapDefaults,
  getTileConfig,
  getFeatureFlags,
  getAllSettings,
  updateSettings,
  resetSettings,
  getConfigMode,
  getApiKeyStatus,
  getBranding,
  updateBranding,
  getEnabledPlugins,
  getEnterpriseOnlyTabs,
  getNotificationStatus,
  sendTestNotification,
} from '@/api/settings';

// --- Public hooks (used by non-admin pages) ---

export function useBasemaps() {
  return useQuery({
    queryKey: queryKeys.settings.basemaps,
    queryFn: getBasemaps,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

export function useMapDefaults() {
  return useQuery({
    queryKey: queryKeys.settings.mapDefaults,
    queryFn: getMapDefaults,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

export function useTileConfig() {
  return useQuery({
    queryKey: queryKeys.settings.tileConfig,
    queryFn: getTileConfig,
    staleTime: 300_000,
    gcTime: 30 * 60_000,
  });
}

export function useEnabledPlugins() {
  return useQuery({
    queryKey: queryKeys.settings.enabledPlugins,
    queryFn: getEnabledPlugins,
    staleTime: 60_000,
    gcTime: 30 * 60_000,
  });
}

export function useFeatureFlags() {
  return useQuery({
    queryKey: queryKeys.settings.featureFlags,
    queryFn: getFeatureFlags,
    staleTime: 60_000,
    gcTime: 30 * 60_000,
  });
}

// --- Unified admin hooks ---

export function useAllSettings(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.settings.allSettings,
    queryFn: getAllSettings,
    enabled: options?.enabled,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

export function useConfigMode() {
  return useQuery({
    queryKey: queryKeys.settings.configMode,
    queryFn: getConfigMode,
    staleTime: Infinity,
  });
}

export function useApiKeyStatus() {
  return useQuery({
    queryKey: queryKeys.settings.apiKeyStatus,
    queryFn: getApiKeyStatus,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

// Phase 279 ADMIN-03 (M-03): server-driven enterprise-tab list. The backend
// _ENTERPRISE_ONLY_TABS frozenset is the canonical source; AdminSidebar reads
// the list via this hook and falls back to a local default when the API is
// unavailable so the sidebar still renders during boot/network failures.
// Tabs rarely change (currently only branding + appearance), so a long
// staleTime is safe and avoids re-fetching on every admin route navigation.
export function useEnterpriseOnlyTabs() {
  return useQuery({
    queryKey: queryKeys.settings.enterpriseTabs,
    queryFn: getEnterpriseOnlyTabs,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    retry: 1,
  });
}

// RES-N8: surface the specific API error message alongside the generic
// "save failed" copy so the user can distinguish validation errors from
// network / auth errors. `formatMutationError` lives in lib/error-map.ts.

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Record<string, unknown>) => updateSettings(settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
      toast.success(i18n.t('settingsToasts.saved'));
    },
    onError: (err) => {
      toast.error(formatMutationError('settingsToasts.saveFailed', err));
    },
  });
}

export function useBranding() {
  return useQuery({
    queryKey: queryKeys.settings.branding,
    queryFn: getBranding,
    staleTime: 60_000,
    gcTime: 30 * 60_000,
  });
}

export function useUpdateBranding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: updateBranding,
    onSuccess: () => {
      // fix(#435): DATA-08 — was `settings.branding` alone. Branding is also
      // served inside the unified `settings.allSettings` payload, which sits
      // beside it rather than under it, so the admin Settings page kept showing
      // pre-save values. The `settings.all` prefix covers both, and matches
      // what every sibling settings mutation already does.
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
      toast.success(i18n.t('settingsToasts.saved'));
    },
    onError: (err) => {
      toast.error(formatMutationError('settingsToasts.saveFailed', err));
    },
  });
}

export function useResetSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keys: string[]) => resetSettings(keys),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
      toast.success(i18n.t('settingsToasts.resetSuccess'));
    },
    onError: (err) => {
      toast.error(formatMutationError('settingsToasts.resetFailed', err));
    },
  });
}

// Phase 1229 Plan 03 — notification status + test-send hooks (NOTIF-06).

/** Query: GET /settings/notifications/status/ — booleans only, no secrets. */
export function useNotificationStatus() {
  return useQuery({
    queryKey: queryKeys.settings.notificationStatus,
    queryFn: getNotificationStatus,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

/** Mutation: POST /settings/notifications/test/ — triggers a canned test send through configured channels. */
export function useSendTestNotification() {
  return useMutation({
    mutationFn: sendTestNotification,
  });
}
