import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { GroupList } from '@/components/admin/GroupList';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function AdminGroupsPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle(t('common:pageTitle.adminGroups'));

  return (
    <>
      <PageHeader title={t('groups.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <GroupList />
    </>
  );
}
