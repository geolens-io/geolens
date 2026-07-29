import { Navigate, Outlet } from 'react-router';
import { LoadingState } from '@/components/layout/LoadingState';
import { usePermissions } from '@/hooks/use-permissions';
import { useEdition } from '@/hooks/use-edition';
import { useSettingsAdmin } from '@/hooks/use-settings-admin';
import type { Capability } from '@/lib/capabilities';

export function AdminRoute() {
  const { can, isLoading } = usePermissions();
  const { isLoading: editionLoading } = useEdition();
  const settingsAdmin = useSettingsAdmin();

  if (isLoading) return <LoadingState />;
  if (can('manage_users') || can('manage_settings')) return <Outlet />;
  // fix(#817): a multi-tenant fleet operator can hold manage_tenants without
  // manage_users/manage_settings — admit them so the AdminSettingsRoute they
  // are authorized for is reachable. Checked after the plain capabilities so
  // the common single-tenant path never waits on the edition query.
  if (editionLoading) return <LoadingState />;
  if (settingsAdmin) return <Outlet />;

  return <Navigate to="/" replace />;
}

export function AdminCapabilityRoute({ capability }: { capability: Capability }) {
  const { can, isLoading } = usePermissions();

  if (isLoading) return <LoadingState />;
  if (!can(capability)) return <Navigate to="/admin" replace />;

  return <Outlet />;
}

// fix(#817): the /settings/* and /config-ops/* APIs are gated mode-aware
// (manage_settings single-tenant, manage_tenants multi-tenant), so the route
// gate must switch the same way — a plain manage_settings gate admitted
// multi-tenant per-tenant admins whose every settings request 403s.
export function AdminSettingsRoute() {
  const { isLoading: permissionsLoading } = usePermissions();
  const { isLoading: editionLoading } = useEdition();
  const allowed = useSettingsAdmin();

  if (permissionsLoading || editionLoading) return <LoadingState />;
  if (!allowed) return <Navigate to="/admin" replace />;

  return <Outlet />;
}

export function AdminIndexRoute() {
  const { can, isLoading } = usePermissions();
  const { isLoading: editionLoading } = useEdition();
  const settingsAdmin = useSettingsAdmin();

  if (isLoading) return <LoadingState />;
  if (can('manage_users')) return <Navigate to="/admin/overview" replace />;
  if (can('manage_settings')) return <Navigate to="/admin/audit" replace />;
  // fix(#817): land a manage_tenants-only fleet operator on the settings
  // pages they are authorized for (neither overview nor audit admits them).
  if (editionLoading) return <LoadingState />;
  if (settingsAdmin) return <Navigate to="/admin/settings/general" replace />;
  return <Navigate to="/" replace />;
}
