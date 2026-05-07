import { useLocation, Link, NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuBadge,
  SidebarHeader,
  SidebarFooter,
  SidebarRail,
} from '@/components/ui/sidebar';
import {
  LayoutDashboard,
  Users,
  Briefcase,
  ScrollText,
  Link2,
  Wrench,
  Settings,
  Shield,
  Brain,
  Globe,
  Map,
  HardDrive,
  Paintbrush,
  Lock,
  ArrowLeft,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { usePendingCount, useFailedJobCount } from '@/hooks/use-admin';
import { useEdition } from '@/hooks/use-edition';
import { useEnterpriseOnlyTabs } from '@/hooks/use-settings';

const overviewItems = [
  { labelKey: 'adminNav.overview', to: '/admin/overview', icon: LayoutDashboard },
] as const;

type OperationItem = {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  badgeKey?: 'pending' | 'failed';
  enterpriseOnly?: boolean;
};

const operationsItems: readonly OperationItem[] = [
  { labelKey: 'adminNav.users', to: '/admin/users', icon: Users, badgeKey: 'pending' },
  { labelKey: 'adminNav.jobs', to: '/admin/jobs', icon: Briefcase, badgeKey: 'failed' },
  { labelKey: 'adminNav.auditLog', to: '/admin/audit', icon: ScrollText },
  { labelKey: 'adminNav.sharedMaps', to: '/admin/shared-maps', icon: Link2 },
  { labelKey: 'adminNav.saml', to: '/admin/saml', icon: Lock, enterpriseOnly: true },
];

// Phase 279 ADMIN-03 (M-03): server-driven enterprise-tab list. Used as the
// fallback when the /settings/enterprise-tabs/ endpoint is unreachable
// (boot, network failure, transient API outage). Must stay in sync with the
// backend `_ENTERPRISE_ONLY_TABS` frozenset in
// `backend/app/modules/settings/router.py` so community sidebars never flash
// forbidden tabs. The hook below is the canonical source — this fallback is
// only the last-resort default during the brief window before the first
// fetch completes (or during prolonged API failures).
const FALLBACK_ENTERPRISE_ONLY_TABS: string[] = ['branding', 'appearance'];

// Declarative settings-nav entries. The `tabKey` (when set) is the Settings
// tab key the route corresponds to (e.g. '/admin/settings/appearance' →
// 'appearance'); the enterpriseOnly flag is derived from the server-driven
// set inside the component below. Entries without a tabKey (config-ops) are
// not Settings tabs — they have a static enterpriseOnly flag.
type SettingsNavBaseItem = {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  tabKey?: string; // Settings tab key (omitted for non-tab routes)
  enterpriseOnly?: boolean; // Static fallback for non-tab routes only
};

const settingsItemsBase: readonly SettingsNavBaseItem[] = [
  { labelKey: 'admin:settings.tabs.general', to: '/admin/settings/general', icon: Settings, tabKey: 'general' },
  { labelKey: 'admin:settings.tabs.auth', to: '/admin/settings/auth', icon: Shield, tabKey: 'auth' },
  { labelKey: 'admin:settings.tabs.ai', to: '/admin/settings/ai', icon: Brain, tabKey: 'ai' },
  { labelKey: 'admin:settings.tabs.network', to: '/admin/settings/network', icon: Globe, tabKey: 'network' },
  { labelKey: 'admin:settings.tabs.storage', to: '/admin/settings/storage', icon: HardDrive, tabKey: 'storage' },
  { labelKey: 'admin:settings.tabs.map', to: '/admin/settings/map', icon: Map, tabKey: 'map' },
  { labelKey: 'admin:settings.tabs.appearance', to: '/admin/settings/appearance', icon: Paintbrush, tabKey: 'appearance' },
  { labelKey: 'admin:settings.tabs.permissions', to: '/admin/settings/permissions', icon: Lock, tabKey: 'permissions' },
  // /admin/config-ops is not a Settings tab — it has its own route. Its
  // enterprise gating is independent of the Settings-tab registry.
  { labelKey: 'adminNav.configOps', to: '/admin/config-ops', icon: Wrench, enterpriseOnly: false },
];

/**
 * Admin section navigation sidebar.
 *
 * Renders the admin navigation tree (Overview, Users, Jobs, Audit, Shared Maps,
 * Settings sub-tabs, Config Ops) with active-route highlighting, badge counts
 * for pending users and failed jobs (live via `usePendingCount` /
 * `useFailedJobCount`), and visibility filtering for `enterpriseOnly` items
 * via the `useEdition` hook.
 */
export function AdminSidebar() {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const { data: pendingCount } = usePendingCount();
  const { data: failedJobCount } = useFailedJobCount();
  const { isEnterprise } = useEdition();
  const { data: enterpriseTabsData } = useEnterpriseOnlyTabs();

  // Phase 279 ADMIN-03 (M-03): derive each Settings-tab's enterpriseOnly flag
  // from the server-driven list. Falls back to the local default when the
  // hook is loading or has errored so the sidebar still renders cleanly
  // during boot/network failures (no flash of forbidden tabs in community).
  const enterpriseTabKeys = enterpriseTabsData?.tabs ?? FALLBACK_ENTERPRISE_ONLY_TABS;
  const settingsItems = settingsItemsBase.map(item => ({
    ...item,
    enterpriseOnly:
      item.tabKey !== undefined
        ? enterpriseTabKeys.includes(item.tabKey)
        : item.enterpriseOnly ?? false,
  }));

  const visibleSettingsItems = settingsItems.filter(item => !item.enterpriseOnly || isEnterprise);
  const visibleOperationsItems = operationsItems.filter(item => !item.enterpriseOnly || isEnterprise);

  const badgeCounts: Record<string, number | undefined> = {
    pending: pendingCount,
    failed: failedJobCount,
  };

  return (
    <Sidebar collapsible="icon" variant="sidebar" side="left">
      <SidebarHeader className="px-4 py-3 group-data-[collapsible=icon]:hidden">
        <span className="text-sm font-semibold text-sidebar-foreground">{t('adminNav.admin')}</span>
      </SidebarHeader>
      <SidebarContent>
        {/* Overview */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {overviewItems.map(({ labelKey, to, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === to}
                    tooltip={t(labelKey)}
                  >
                    <NavLink to={to}>
                      <Icon />
                      <span>{t(labelKey)}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Operations */}
        <SidebarGroup>
          <SidebarGroupLabel>{t('adminNav.operations')}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visibleOperationsItems.map(({ labelKey, to, icon: Icon, badgeKey }) => {
                const count = badgeKey ? badgeCounts[badgeKey] : undefined;
                return (
                  <SidebarMenuItem key={to}>
                    <SidebarMenuButton
                      asChild
                      isActive={pathname.startsWith(to)}
                      tooltip={t(labelKey)}
                    >
                      <NavLink to={to}>
                        <Icon />
                        <span>{t(labelKey)}</span>
                      </NavLink>
                    </SidebarMenuButton>
                    {count !== undefined && count > 0 && (
                      <SidebarMenuBadge>{count}</SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Settings */}
        <SidebarGroup>
          <SidebarGroupLabel>{t('adminNav.settings')}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visibleSettingsItems.map(({ labelKey, to, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === to || pathname.startsWith(to)}
                    tooltip={t(labelKey)}
                  >
                    <NavLink to={to}>
                      <Icon />
                      <span>{t(labelKey)}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip={t('adminNav.backToApp')}>
              {/* CLEAN-N5: search workspace is "/" after landing page removal. */}
              <Link to="/">
                <ArrowLeft className="rtl-mirror" />
                <span>{t('adminNav.backToApp')}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
