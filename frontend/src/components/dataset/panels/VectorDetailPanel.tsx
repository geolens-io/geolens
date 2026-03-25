import { useTranslation } from 'react-i18next';
import type { DatasetResponse } from '@/types/api';
import type { DatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { OverviewTab } from '../tabs/OverviewTab';
import { MetadataTab } from '../tabs/MetadataTab';
import { DataTab } from '../tabs/DataTab';
import { StructureTab } from '../tabs/StructureTab';
import { AccessTab } from '../tabs/AccessTab';

export type PendingDraftField =
  | 'summary'
  | 'lineage_summary'
  | 'source_url'
  | 'source_organization'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement';

export interface DetailPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  datasetId: string;
  activeTab: string;
  onTabChange: (tab: string) => void;
  resolveDraftValue: (field: PendingDraftField) => string;
  stagePendingDraft: (field: PendingDraftField, value: string) => void;
  handleDraftDirtyChange: (field: PendingDraftField, isDirty: boolean) => void;
  onNavigateToValidationField: (field: string) => void;
}

export function VectorDetailPanel(props: DetailPanelProps) {
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

  const isTable = dataset.record_type === 'table';

  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <TabsList className="overflow-x-auto w-full sticky top-0 z-10 bg-background border-b">
        <TabsTrigger value="overview">{t('tabs.overview')}</TabsTrigger>
        <TabsTrigger value="metadata">{t('tabs.metadata')}</TabsTrigger>
        {!isTable && <TabsTrigger value="data">{t('tabs.data')}</TabsTrigger>}
        <TabsTrigger value="structure">{t('tabs.structure')}</TabsTrigger>
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
      {!isTable && (
        <TabsContent value="data" className="space-y-6">
          <DataTab datasetId={datasetId} canEdit={canEdit} />
        </TabsContent>
      )}
      <TabsContent value="structure" className="space-y-6">
        <StructureTab
          datasetId={datasetId}
          canEdit={canEdit}
          columnInfo={dataset.column_info}
          capability={capabilities.theme_category}
          tableName={dataset.table_name}
          recordType={dataset.record_type}
        />
      </TabsContent>
      <TabsContent value="access" className="space-y-6">
        <AccessTab dataset={dataset} datasetId={datasetId} />
      </TabsContent>
    </Tabs>
  );
}
