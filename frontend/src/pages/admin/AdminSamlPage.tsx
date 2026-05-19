/**
 * Admin SAML SSO configuration page.
 *
 * Page-level edition gating (Phase 217 D-14, updated Phase 1054-03 ROUTE-01):
 * - Community edition: renders an "Enterprise Feature" notice that keeps the URL
 *   at /admin/saml so operators who arrive via bookmark or copied URL get a clear
 *   signal rather than a silent vanish. The notice does NOT fetch data from the
 *   gated /auth/saml/* endpoints (SamlProvidersSection is not rendered).
 * - Enterprise edition: renders the full SamlProvidersSection.
 *
 * Three-layer access-control still holds (T-217-04-EDITION):
 *   Layer 1 — backend: require_enterprise() returns 404 on /auth/saml/*.
 *   Layer 2 — sidebar nav: enterpriseOnly nav-item filter hides the link.
 *   Layer 3 — this page: community path renders a notice (previously: Navigate away).
 * The security stance is identical — community-edition browser never calls
 * /auth/saml/* regardless of whether layer 3 redirects or renders a notice.
 */

import { useTranslation } from 'react-i18next';
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
    return (
      <>
        <PageHeader
          title={t('saml.enterpriseOnly.title')}
          description={t('saml.enterpriseOnly.description')}
          breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]}
        />
        <div className="rounded-xl border border-border bg-card p-6 max-w-2xl">
          <h2 className="text-lg font-medium mb-2">{t('saml.enterpriseOnly.heading')}</h2>
          <p className="text-sm text-muted-foreground mb-4">
            {t('saml.enterpriseOnly.body')}
          </p>
          <a
            href="https://docs.getgeolens.com/guides/enterprise/saml/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline hover:text-primary/80 text-sm"
          >
            {t('saml.enterpriseOnly.docsLink')}
          </a>
        </div>
      </>
    );
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
