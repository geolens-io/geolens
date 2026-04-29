/**
 * Admin SAML SSO configuration page.
 *
 * Page-level edition gating (Phase 217 D-14): redirects to /admin if the
 * deployment is not enterprise. This is a belt-and-suspenders defense behind
 * the backend's `require_enterprise()` 404 on `/auth/saml/*` and the sidebar
 * nav-item filter — three layers of "SAML is enterprise-only" enforcement
 * (T-217-04-EDITION).
 */

import { useTranslation } from 'react-i18next';
import { Navigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { LoadingState } from '@/components/layout/LoadingState';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useEdition } from '@/hooks/use-edition';
import { SamlProvidersSection } from '@/components/admin/saml/SamlProvidersSection';

export function AdminSamlPage() {
  const { t } = useTranslation('admin');
  const { isEnterprise, isLoading } = useEdition();
  useDocumentTitle(t('common:pageTitle.adminSaml'));

  if (isLoading) {
    return <LoadingState />;
  }

  if (!isEnterprise) {
    // Belt-and-suspenders: backend also returns 404 from /auth/saml/* in
    // community, so an admin who pastes the URL directly hits a redirect first
    // (UX) and the API gates the data anyway (security).
    return <Navigate to="/admin" replace />;
  }

  return (
    <>
      <PageHeader
        title={t('saml.title')}
        description={t('saml.description')}
        breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]}
      />
      <SamlProvidersSection />
    </>
  );
}
