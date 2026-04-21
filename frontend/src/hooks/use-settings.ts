import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { ApiError } from '@/api/client';
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
  getEnabledWidgets,
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

export function useEnabledWidgets() {
  return useQuery({
    queryKey: queryKeys.settings.enabledWidgets,
    queryFn: getEnabledWidgets,
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

// RES-N8: surface the specific API error message alongside the generic
// "save failed" copy so the user can distinguish validation errors from
// network / auth errors. ApiError carries a translated message already;
// fallback to String(err) for unexpected error shapes.
function formatMutationError(fallbackKey: string, err: unknown): string {
  // i18next ``.t()`` returns ``unknown`` under the newer generic; narrow
  // at the boundary so the string concatenation below type-checks.
  const base = i18n.t(fallbackKey) as string;
  if (err instanceof ApiError && err.message) {
    return `${base}: ${err.message}`;
  }
  if (err instanceof Error && err.message) {
    return `${base}: ${err.message}`;
  }
  return base;
}

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
      qc.invalidateQueries({ queryKey: queryKeys.settings.branding });
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
