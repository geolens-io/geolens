import { useTranslation } from 'react-i18next';
import { useParams, Navigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { EnvOnlyBanner } from '@/components/admin/settings/EnvOnlyBanner';
import { SettingsGeneralTab } from '@/components/admin/settings/SettingsGeneralTab';
import { SettingsAuthTab } from '@/components/admin/settings/SettingsAuthTab';
import { SettingsAITab } from '@/components/admin/settings/SettingsAITab';
import { SettingsNetworkTab } from '@/components/admin/settings/SettingsNetworkTab';
import { SettingsStorageTab } from '@/components/admin/settings/SettingsStorageTab';
import { SettingsAppearanceTab } from '@/components/admin/settings/SettingsAppearanceTab';
import { SettingsPermissionsTab } from '@/components/admin/settings/SettingsPermissionsTab';
import { useAllSettings, useConfigMode, useUpdateSettings, useResetSettings } from '@/hooks/use-settings';
import type { SettingItem } from '@/api/settings';
import { useDocumentTitle } from '@/hooks/use-document-title';

const TAB_KEYS = ['general', 'auth', 'ai', 'network', 'storage', 'appearance', 'permissions'] as const;
type TabKey = typeof TAB_KEYS[number];

const TAB_LABELS: Record<TabKey, string> = {
  general: 'settings.tabs.general',
  auth: 'settings.tabs.auth',
  ai: 'settings.tabs.ai',
  network: 'settings.tabs.network',
  storage: 'settings.tabs.storage',
  appearance: 'settings.tabs.appearance',
  permissions: 'settings.tabs.permissions',
};

const TAB_COMPONENTS: Record<TabKey, React.ComponentType<{
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
}>> = {
  general: SettingsGeneralTab,
  auth: SettingsAuthTab,
  ai: SettingsAITab,
  network: SettingsNetworkTab,
  storage: SettingsStorageTab,
  appearance: SettingsAppearanceTab,
  permissions: SettingsPermissionsTab,
};

export function AdminSettingsPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle('Admin Settings');
  const { tab } = useParams<{ tab: string }>();
  const { data: allSettings, isLoading, isError, error } = useAllSettings();
  const { data: configMode } = useConfigMode();
  const updateMutation = useUpdateSettings();
  const resetMutation = useResetSettings();

  const activeTab = (tab && TAB_KEYS.includes(tab as TabKey) ? tab : null) as TabKey | null;

  if (!activeTab) {
    return <Navigate to="/admin/settings/general" replace />;
  }

  const envOnly = configMode?.env_only ?? allSettings?.env_only ?? false;

  function handleSave(changes: Record<string, unknown>) {
    updateMutation.mutate(changes);
  }

  function handleReset(key: string) {
    resetMutation.mutate([key]);
  }

  if (isLoading) {
    return (
      <>
        <PageHeader
          title={t(TAB_LABELS[activeTab], activeTab)}
          breadcrumbs={[
            { label: t('common:adminNav.admin'), to: '/admin' },
            { label: t('settings.page.title', 'Settings'), to: '/admin/settings/general' },
          ]}
        />
        <div className="space-y-4">
          <Skeleton className="h-10 w-96" />
          <Skeleton className="h-64 w-full" />
        </div>
      </>
    );
  }

  if (isError) {
    return (
      <>
        <PageHeader
          title={t(TAB_LABELS[activeTab], activeTab)}
          breadcrumbs={[
            { label: t('common:adminNav.admin'), to: '/admin' },
            { label: t('settings.page.title', 'Settings'), to: '/admin/settings/general' },
          ]}
        />
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {t('settings.page.loadFailed', { message: error?.message ?? t('settings.page.unknownError') })}
        </div>
      </>
    );
  }

  const tabs = allSettings?.tabs ?? {};
  const TabComponent = TAB_COMPONENTS[activeTab];

  return (
    <>
      <PageHeader
        title={t(TAB_LABELS[activeTab], activeTab)}
        breadcrumbs={[
          { label: t('common:adminNav.admin'), to: '/admin' },
          { label: t('settings.page.title', 'Settings'), to: '/admin/settings/general' },
        ]}
      />

      <div className="space-y-6">
        <EnvOnlyBanner />

        <TabComponent
          settings={tabs[activeTab] ?? []}
          envOnly={envOnly}
          onSave={handleSave}
          onReset={handleReset}
          isSaving={updateMutation.isPending}
        />
      </div>
    </>
  );
}
