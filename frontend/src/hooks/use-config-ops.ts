import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import {
  exportConfig,
  dryRunImport,
  importConfig,
  validateConnectivity,
} from '@/api/config-ops';
import type {
  ConfigImportRequest,
  ImportMode,
  DryRunResult,
  ImportResult,
  ConnectivityResult,
} from '@/api/config-ops';

export function useExportConfig() {
  return useMutation({
    mutationFn: exportConfig,
    onSuccess: (data) => {
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `geolens-config-${data.exported_at.slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success(i18n.t('configOps.exported'));
    },
    onError: (err: Error) => {
      toast.error(err.message || i18n.t('configOps.exportFailed'));
    },
  });
}

export function useDryRunImport() {
  return useMutation<
    DryRunResult,
    Error,
    { data: ConfigImportRequest; mode: ImportMode }
  >({
    mutationFn: ({ data, mode }) => dryRunImport(data, mode),
    onError: (err: Error) => {
      toast.error(err.message || i18n.t('configOps.previewFailed'));
    },
  });
}

export function useValidateConnectivity() {
  return useMutation<ConnectivityResult, Error>({
    mutationFn: validateConnectivity,
    onError: (err: Error) => {
      toast.error(err.message || i18n.t('configOps.validateFailed'));
    },
  });
}

export function useImportConfig() {
  return useMutation<
    ImportResult,
    Error,
    { data: ConfigImportRequest; mode: ImportMode }
  >({
    mutationFn: ({ data, mode }) => importConfig(data, mode),
    onSuccess: (result) => {
      const parts: string[] = [];
      if (result.settings_applied > 0) parts.push(i18n.t('configOps.settingsApplied', { count: result.settings_applied }));
      if (result.settings_skipped > 0) parts.push(i18n.t('configOps.skipped', { count: result.settings_skipped }));
      if (result.oauth_created > 0) parts.push(i18n.t('configOps.providersCreated', { count: result.oauth_created }));
      if (result.oauth_updated > 0) parts.push(i18n.t('configOps.providersUpdated', { count: result.oauth_updated }));
      if (result.oauth_deleted > 0) parts.push(i18n.t('configOps.providersDeleted', { count: result.oauth_deleted }));
      toast.success(parts.length > 0 ? parts.join(', ') : i18n.t('configOps.importComplete'));
    },
    onError: (err: Error) => {
      toast.error(err.message || i18n.t('configOps.importFailed'));
    },
  });
}

