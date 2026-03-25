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
  HardDrive,
  Palette,
  Lock,
  ArrowLeft,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { usePendingCount, useFailedJobCount } from '@/hooks/use-admin';

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
  { labelKey: 'admin:settings.tabs.general', to: '/admin/settings/general', icon: Settings },
  { labelKey: 'admin:settings.tabs.auth', to: '/admin/settings/auth', icon: Shield },
  { labelKey: 'admin:settings.tabs.ai', to: '/admin/settings/ai', icon: Brain },
  { labelKey: 'admin:settings.tabs.network', to: '/admin/settings/network', icon: Globe },
  { labelKey: 'admin:settings.tabs.storage', to: '/admin/settings/storage', icon: HardDrive },
  { labelKey: 'admin:settings.tabs.appearance', to: '/admin/settings/appearance', icon: Palette },
  { labelKey: 'admin:settings.tabs.permissions', to: '/admin/settings/permissions', icon: Lock },
  { labelKey: 'adminNav.configOps', to: '/admin/config-ops', icon: Wrench },
] as const;

export function AdminSidebar() {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const { data: pendingCount } = usePendingCount();
  const { data: failedJobCount } = useFailedJobCount();

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
              {settingsItems.map(({ labelKey, to, icon: Icon }) => (
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
