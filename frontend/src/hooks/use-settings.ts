import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
} from '@/api/settings';

// --- Public hooks (used by non-admin pages) ---

export function useBasemaps() {
  return useQuery({
    queryKey: ['settings', 'basemaps'],
    queryFn: getBasemaps,
    staleTime: 60_000,
  });
}

export function useMapDefaults() {
  return useQuery({
    queryKey: ['settings', 'map-defaults'],
    queryFn: getMapDefaults,
    staleTime: 60_000,
  });
}

export function useTileConfig() {
  return useQuery({
    queryKey: ['settings', 'tile-config'],
    queryFn: getTileConfig,
    staleTime: 300_000,
  });
}

// --- Unified admin hooks ---

export function useAllSettings() {
  return useQuery({
    queryKey: ['settings', 'all'],
    queryFn: getAllSettings,
  });
}

export function useConfigMode() {
  return useQuery({
    queryKey: ['settings', 'config-mode'],
    queryFn: getConfigMode,
  });
}

export function useApiKeyStatus() {
  return useQuery({
    queryKey: ['settings', 'api-key-status'],
    queryFn: getApiKeyStatus,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Record<string, unknown>) => updateSettings(settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] });
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
      qc.invalidateQueries({ queryKey: ['settings'] });
      toast.success(i18n.t('settingsToasts.resetSuccess'));
    },
    onError: () => {
      toast.error(i18n.t('settingsToasts.resetFailed'));
    },
  });
}
