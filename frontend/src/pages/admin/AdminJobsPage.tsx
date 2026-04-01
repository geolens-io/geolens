import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { JobList } from '@/components/admin/JobList';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function AdminJobsPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle(t('common:pageTitle.adminJobs'));

  return (
    <>
      <PageHeader title={t('jobs.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <JobList />
    </>
  );
}
