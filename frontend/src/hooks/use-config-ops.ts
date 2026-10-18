import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { triggerDownload } from '@/lib/download';
import { queryKeys } from '@/lib/query-keys';
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
      triggerDownload(blob, `geolens-config-${data.exported_at.slice(0, 10)}.json`);
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
  const queryClient = useQueryClient();

  return useMutation<
    ImportResult,
    Error,
    { data: ConfigImportRequest; mode: ImportMode; previewToken?: string | null }
  >({
    mutationFn: ({ data, mode, previewToken }) =>
      importConfig(data, mode, previewToken),
    onSuccess: (result) => {
      // AdminConfigOpsPage mounts no useQuery of its own, but invalidateQueries marks
      // a cached-but-unmounted entry stale so it refetches on next mount, which is how
      // the Settings tabs and the login page pick the import up. Each key below can
      // exist in this user's client.
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.authConfig.config });
      // The login page's OAuth buttons. Sibling admin surfaces that mutate the same
      // providers use useInvalidateAuthProviders (hooks/use-auth-providers.ts); this
      // one stays inline because it invalidates far more than the provider pair.
      queryClient.invalidateQueries({ queryKey: queryKeys.authConfig.oauthProviders });
      // The two AI-readiness keys below are a mutually-exclusive pair, not a
      // duplicate: useAIAvailability mounts admin.aiStatus when useAIStatusReader() is
      // true and maps.aiAvailability when false, so at most one holds an entry and
      // each covers an operator class the other misses.
      //
      // The second line looks dead because validate_permission_matrix
      // (auth/permissions.py) grants manage_settings to `admin` alone, who also
      // holds manage_users, making every config-ops admin a status reader. That holds
      // only for the stored matrix; usePermissions() reads me_permissions, which
      // resolves through PermissionExtension.check_permission. An enterprise overlay
      // can grant manage_settings and use_ai_chat without manage_users, and that
      // operator mounts maps.aiAvailability. Community's DefaultPermissionExtension
      // reads the stored matrix, hence the dead look by default.
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiStatus });
      queryClient.invalidateQueries({ queryKey: queryKeys.maps.aiAvailability });

      const parts: string[] = [];
      if (result.settings_applied > 0) parts.push(i18n.t('configOps.settingsApplied', { count: result.settings_applied }));
      if (result.settings_skipped > 0) parts.push(i18n.t('configOps.skipped', { count: result.settings_skipped }));
      if (result.oauth_created > 0) parts.push(i18n.t('configOps.providersCreated', { count: result.oauth_created }));
      if (result.oauth_updated > 0) parts.push(i18n.t('configOps.providersUpdated', { count: result.oauth_updated }));
      if (result.oauth_deleted > 0) parts.push(i18n.t('configOps.providersDeleted', { count: result.oauth_deleted }));
      if (result.oauth_accounts_deleted > 0) parts.push(i18n.t('configOps.accountsDeleted', { count: result.oauth_accounts_deleted }));
      toast.success(parts.length > 0 ? parts.join(', ') : i18n.t('configOps.importComplete'));
    },
    onError: (err: Error) => {
      toast.error(err.message || i18n.t('configOps.importFailed'));
    },
  });
}
