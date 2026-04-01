import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { StatsOverview } from '@/components/admin/StatsOverview';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function AdminOverviewPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle(t('common:pageTitle.adminOverview'));

  return (
    <>
      <PageHeader title={t('overview.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <StatsOverview />
    </>
  );
}
