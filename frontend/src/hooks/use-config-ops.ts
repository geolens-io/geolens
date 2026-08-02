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
      // chore(#1021): AdminConfigOpsPage mounts no useQuery of its own, so none of
      // these entries is populated by this surface. That alone does not make them
      // inert: invalidateQueries marks a cached-but-unmounted entry stale and it
      // refetches on next mount, which is exactly how the Settings tabs and the login
      // page pick the import up. The test is whether an entry can exist in THIS
      // user's client at all, and for each key below one can.
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.authConfig.config });
      // chore(#1021): the login page's OAuth buttons. The sibling admin surfaces that
      // mutate the same providers (SettingsAuthTab, SamlProvidersSection) invalidate
      // only settingsOAuth.providers and miss this key. That gap is #1117, the inverse
      // of this issue, and is not fixed here.
      queryClient.invalidateQueries({ queryKey: queryKeys.authConfig.oauthProviders });
      // chore(#1021): the two AI-readiness keys below are a mutually-exclusive PAIR,
      // not a duplicate. useAIAvailability mounts admin.aiStatus when
      // useAIStatusReader() is true and maps.aiAvailability when it is false, so at
      // most one holds an entry in a given session and each covers an operator class
      // the other misses. Deleting either half silently drops one of them.
      //
      // The second line reads as dead, and that reading is wrong. The argument for
      // dead goes: config-ops gates on useSettingsAdmin(), and
      // validate_permission_matrix (backend/app/modules/auth/permissions.py) grants
      // manage_settings to `admin` alone while refusing to let that role drop
      // manage_users, so every config-ops admin is also a status reader. That argument
      // got this line deleted once and had to be reverted. It holds only for the
      // STORED matrix, which is not the capability authority: me_permissions
      // (backend/app/modules/auth/router.py) resolves every capability through
      // PermissionExtension.check_permission, and that is what usePermissions() reads.
      // An enterprise overlay can therefore grant manage_settings and use_ai_chat
      // without manage_users. That operator reaches config-ops with canReadStatus
      // false, mounts maps.aiAvailability, and owns the entry this line invalidates.
      // Community deployments use DefaultPermissionExtension, which does read the
      // stored matrix, which is exactly why the line looks dead by default. See the
      // codex P2 on #1121.
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
