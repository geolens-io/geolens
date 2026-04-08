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

const overviewItems = [
  { labelKey: 'adminNav.overview', to: '/admin/overview', icon: LayoutDashboard },
] as const;

type OperationItem = {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  badgeKey?: 'pending' | 'failed';
};

const operationsItems: readonly OperationItem[] = [
  { labelKey: 'adminNav.users', to: '/admin/users', icon: Users, badgeKey: 'pending' },
  { labelKey: 'adminNav.jobs', to: '/admin/jobs', icon: Briefcase, badgeKey: 'failed' },
  { labelKey: 'adminNav.auditLog', to: '/admin/audit', icon: ScrollText },
  { labelKey: 'adminNav.sharedMaps', to: '/admin/shared-maps', icon: Link2 },
];

const settingsItems = [
  { labelKey: 'admin:settings.tabs.general', to: '/admin/settings/general', icon: Settings, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.auth', to: '/admin/settings/auth', icon: Shield, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.ai', to: '/admin/settings/ai', icon: Brain, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.network', to: '/admin/settings/network', icon: Globe, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.storage', to: '/admin/settings/storage', icon: HardDrive, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.map', to: '/admin/settings/map', icon: Map, enterpriseOnly: false },
  { labelKey: 'admin:settings.tabs.appearance', to: '/admin/settings/appearance', icon: Paintbrush, enterpriseOnly: true },
  { labelKey: 'admin:settings.tabs.permissions', to: '/admin/settings/permissions', icon: Lock, enterpriseOnly: false },
  { labelKey: 'adminNav.configOps', to: '/admin/config-ops', icon: Wrench, enterpriseOnly: false },
] as const;

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

  const visibleSettingsItems = settingsItems.filter(item => !item.enterpriseOnly || isEnterprise);

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
              {operationsItems.map(({ labelKey, to, icon: Icon, badgeKey }) => {
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
                <ArrowLeft />
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
