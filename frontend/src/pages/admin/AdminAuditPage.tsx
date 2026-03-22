import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { AuditLogViewer } from '@/components/admin/AuditLogViewer';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function AdminAuditPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle('Admin Audit Log');

  return (
    <>
      <PageHeader title={t('audit.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <AuditLogViewer />
    </>
  );
}
