import { useTranslation } from 'react-i18next';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { OverviewTab } from '../tabs/OverviewTab';
import { MetadataTab } from '../tabs/MetadataTab';
import { SourcesTab } from '../tabs/SourcesTab';
import { AccessTab } from '../tabs/AccessTab';
import type { DetailPanelProps } from './VectorDetailPanel';

export function VrtDetailPanel(props: DetailPanelProps) {
  const { t } = useTranslation('dataset');
  const {
    dataset,
    canEdit,
    capabilities,
    datasetId,
    activeTab,
    onTabChange,
    resolveDraftValue,
    stagePendingDraft,
    handleDraftDirtyChange,
    onNavigateToValidationField,
  } = props;

  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <TabsList className="overflow-x-auto w-full sticky top-0 z-10 bg-background border-b">
        <TabsTrigger value="overview">{t('tabs.overview')}</TabsTrigger>
        <TabsTrigger value="metadata">{t('tabs.metadata')}</TabsTrigger>
        <TabsTrigger value="sources">{t('tabs.sources')}</TabsTrigger>
        <TabsTrigger value="access">{t('tabs.access', { defaultValue: 'Access' })}</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6">
        <OverviewTab
          dataset={dataset}
          canEdit={canEdit}
          capabilities={capabilities}
          summaryValue={resolveDraftValue('summary')}
          onSummaryDraftSave={(value) => stagePendingDraft('summary', value)}
          onSummaryDirtyChange={(isDirty) => handleDraftDirtyChange('summary', isDirty)}
          datasetId={datasetId}
          onNavigateToValidationField={onNavigateToValidationField}
        />
      </TabsContent>
      <TabsContent value="metadata" className="space-y-6">
        <MetadataTab
          dataset={dataset}
          canEdit={canEdit}
          capabilities={capabilities}
          draftValues={{
            lineage_summary: resolveDraftValue('lineage_summary'),
            source_url: resolveDraftValue('source_url'),
            source_organization: resolveDraftValue('source_organization'),
            update_frequency: resolveDraftValue('update_frequency'),
            usage_constraints: resolveDraftValue('usage_constraints'),
            access_constraints: resolveDraftValue('access_constraints'),
            sensitivity_classification: resolveDraftValue('sensitivity_classification'),
            quality_statement: resolveDraftValue('quality_statement'),
          }}
          onDraftSave={stagePendingDraft}
          onDraftDirtyChange={handleDraftDirtyChange}
          onNavigateToValidationField={onNavigateToValidationField}
        />
      </TabsContent>
      <TabsContent value="sources" className="space-y-6">
        <SourcesTab dataset={dataset} canEdit={canEdit} datasetId={datasetId} />
      </TabsContent>
      <TabsContent value="access" className="space-y-6">
        <AccessTab dataset={dataset} datasetId={datasetId} />
      </TabsContent>
    </Tabs>
  );
}
