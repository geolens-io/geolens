import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { UserList } from '@/components/admin/UserList';
import { useDocumentTitle } from '@/hooks/use-document-title';

export function AdminUsersPage() {
  const { t } = useTranslation('admin');
  useDocumentTitle('Admin Users');

  return (
    <>
      <PageHeader title={t('users.title')} breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]} />
      <UserList />
    </>
  );
}
