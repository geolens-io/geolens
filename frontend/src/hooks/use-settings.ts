import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import {
  getBasemaps,
  getMapDefaults,
  getTileConfig,
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
    staleTime: 60_000,
  });
}

export function useMapDefaults() {
  return useQuery({
    queryKey: queryKeys.settings.mapDefaults,
    queryFn: getMapDefaults,
    staleTime: 60_000,
  });
}

export function useTileConfig() {
  return useQuery({
    queryKey: queryKeys.settings.tileConfig,
    queryFn: getTileConfig,
    staleTime: 300_000,
  });
}

export function useEnabledWidgets() {
  return useQuery({
    queryKey: queryKeys.settings.enabledWidgets,
    queryFn: getEnabledWidgets,
    staleTime: 60_000,
  });
}

// --- Unified admin hooks ---

export function useAllSettings(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.settings.allSettings,
    queryFn: getAllSettings,
    enabled: options?.enabled,
  });
}

export function useConfigMode() {
  return useQuery({
    queryKey: queryKeys.settings.configMode,
    queryFn: getConfigMode,
  });
}

export function useApiKeyStatus() {
  return useQuery({
    queryKey: queryKeys.settings.apiKeyStatus,
    queryFn: getApiKeyStatus,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Record<string, unknown>) => updateSettings(settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
      toast.success(i18n.t('settingsToasts.saved'));
    },
    onError: () => {
      toast.error(i18n.t('settingsToasts.saveFailed'));
    },
  });
}

export function useBranding() {
  return useQuery({
    queryKey: queryKeys.settings.branding,
    queryFn: getBranding,
    staleTime: 60_000,
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
    onError: () => {
      toast.error(i18n.t('settingsToasts.saveFailed'));
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
    onError: () => {
      toast.error(i18n.t('settingsToasts.resetFailed'));
    },
  });
}
