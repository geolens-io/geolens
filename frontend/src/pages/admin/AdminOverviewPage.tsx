import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { StatsOverview } from '@/components/admin/StatsOverview';
import { Badge } from '@/components/ui/badge';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useEdition } from '@/hooks/use-edition';

export function AdminOverviewPage() {
  const { t } = useTranslation('admin');
  const { isEnterprise, isLoading } = useEdition();
  useDocumentTitle(t('common:pageTitle.adminOverview'));

  return (
    <>
      <PageHeader
        title={t('overview.title')}
        breadcrumbs={[{ label: t('common:adminNav.admin'), to: '/admin' }]}
        actions={
          // feat(#379): edition badge; hidden until the edition query resolves
          // so a licensed instance never flashes "Community".
          isLoading ? null : (
            <Badge variant={isEnterprise ? 'default' : 'secondary'}>
              {isEnterprise ? t('overview.editionEnterprise') : t('overview.editionCommunity')}
            </Badge>
          )
        }
      />
      <StatsOverview />
    </>
  );
}
