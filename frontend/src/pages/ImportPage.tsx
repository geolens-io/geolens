import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageShell } from '@/components/layout/PageShell';
import { PageHeader } from '@/components/layout/PageHeader';
import { UploadForm } from '@/components/import/UploadForm';
import { RegisterForm } from '@/components/import/RegisterForm';
import { ServiceUrlForm } from '@/components/import/ServiceUrlForm';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useDocumentTitle } from '@/hooks/use-document-title';

type Tab = 'upload' | 'register' | 'service';

export function ImportPage() {
  const { t } = useTranslation('import');
  const [activeTab, setActiveTab] = useState<Tab>('upload');
  useDocumentTitle(t('common:pageTitle.import'));

  return (
    <PageShell>
      <PageHeader title={t('title')} />

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as Tab)}>
        <TabsList>
          <TabsTrigger value="upload">{t('tabs.upload')}</TabsTrigger>
          <TabsTrigger value="register">{t('tabs.register')}</TabsTrigger>
          <TabsTrigger value="service">{t('tabs.service')}</TabsTrigger>
        </TabsList>
        <TabsContent value="upload"><UploadForm /></TabsContent>
        <TabsContent value="register"><RegisterForm /></TabsContent>
        <TabsContent value="service"><ServiceUrlForm /></TabsContent>
      </Tabs>
    </PageShell>
  );
}
