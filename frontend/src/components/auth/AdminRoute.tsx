import { Navigate, Outlet } from 'react-router';
import { LoadingState } from '@/components/layout/LoadingState';
import { usePermissions } from '@/hooks/use-permissions';
import type { Capability } from '@/lib/capabilities';

export function AdminRoute() {
  const { can, isLoading } = usePermissions();

  if (isLoading) return <LoadingState />;
  if (!can('manage_users') && !can('manage_settings')) return <Navigate to="/" replace />;

  return <Outlet />;
}

export function AdminCapabilityRoute({ capability }: { capability: Capability }) {
  const { can, isLoading } = usePermissions();

  if (isLoading) return <LoadingState />;
  if (!can(capability)) return <Navigate to="/admin" replace />;

  return <Outlet />;
}

export function AdminIndexRoute() {
  const { can, isLoading } = usePermissions();

  if (isLoading) return <LoadingState />;
  if (can('manage_users')) return <Navigate to="/admin/overview" replace />;
  if (can('manage_settings')) return <Navigate to="/admin/audit" replace />;
  return <Navigate to="/" replace />;
}
