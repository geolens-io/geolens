/**
 * Admin audit-log viewer page.
 *
 * Page-level page guard (Phase 279 ADMIN-08 / L-05): redirects to /admin
 * when the active user lacks the manage_settings capability. Defense-in-depth
 * on top of the backend's require_permission("manage_settings") 403 on
 * /admin/audit-logs/* and the sidebar nav-item filter -- three layers
 * keep the audit log (which exposes resource IDs RBAC would otherwise
 * hide) gated.
 *
 * Phase 281: capability key aligned to the canonical ALL_CAPABILITIES
 * registry (`backend/app/core/permissions.py`). The previous `view_audit`
 * key was not registered server-side, so `useAuth().can('view_audit')` was
 * always false and the guard redirected even for admins.
 */

import { useTranslation } from 'react-i18next';
import { Navigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { LoadingState } from '@/components/layout/LoadingState';
import { AuditLogViewer } from '@/components/admin/AuditLogViewer';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { usePermissions } from '@/hooks/use-permissions';

export function AdminAuditPage() {
  const { t } = useTranslation('admin');
  const { can, isLoading } = usePermissions();
  useDocumentTitle(t('common:pageTitle.adminAuditLog'));

  if (isLoading) {
    return <LoadingState />;
  }

  if (!can('manage_settings')) {
    // Belt-and-suspenders: backend also returns 403 from /admin/audit-logs/
    // via require_permission("manage_settings"). The page-level guard gives
    // non-admin users who paste the URL directly a redirect first (UX) and
    // the API gates the data anyway (security). Phase 279 / L-05, Phase 281.
    return <Navigate to="/admin" replace />;
  }

  return (
    <>
      <PageHeader title={t('audit.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <AuditLogViewer />
    </>
  );
}
