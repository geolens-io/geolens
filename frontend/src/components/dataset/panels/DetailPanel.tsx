import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { DatasetResponse } from '@/types/api';
import type { DatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import type { PendingDraftField } from '@/components/dataset/hooks/use-draft-editing';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { OverviewTab } from '../tabs/OverviewTab';
import { MetadataTab } from '../tabs/MetadataTab';
import { DataTab } from '../tabs/DataTab';
import { StructureTab } from '../tabs/StructureTab';
import { SourcesTab } from '../tabs/SourcesTab';
import { AccessTab } from '../tabs/AccessTab';

export interface DetailPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  activeTab: string;
  onTabChange: (tab: string) => void;
  resolveDraftValue: (field: PendingDraftField) => string;
  stagePendingDraft: (field: PendingDraftField, value: string) => void;
  handleDraftDirtyChange: (field: PendingDraftField, isDirty: boolean) => void;
  onNavigateToValidationField: (field: string) => void;
  isTableExpanded?: boolean;
  onToggleTableExpand?: () => void;
}

export function DetailPanel(props: DetailPanelProps) {
  const { t } = useTranslation('dataset');
  const {
    dataset,
    canEdit,
    capabilities,
    activeTab,
    onTabChange,
    resolveDraftValue,
    stagePendingDraft,
    handleDraftDirtyChange,
    onNavigateToValidationField,
    isTableExpanded,
    onToggleTableExpand,
  } = props;

  const recordType = dataset.record_type;
  const isTable = recordType === 'table';
  const isVrt = recordType === 'vrt_dataset';
  const isVector = recordType === 'vector_dataset' || isTable || !recordType;

  const showData = isVector && !isTable;
  const showStructure = isVector;
  const showSources = isVrt;

  const draftValues = useMemo(() => ({
    lineage_summary: resolveDraftValue('lineage_summary'),
    source_url: resolveDraftValue('source_url'),
    source_organization: resolveDraftValue('source_organization'),
    update_frequency: resolveDraftValue('update_frequency'),
    usage_constraints: resolveDraftValue('usage_constraints'),
    access_constraints: resolveDraftValue('access_constraints'),
    sensitivity_classification: resolveDraftValue('sensitivity_classification'),
    quality_statement: resolveDraftValue('quality_statement'),
  }), [resolveDraftValue]);

  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <TabsList className="overflow-x-auto w-full sticky top-0 z-20 bg-background border-b">
        <TabsTrigger value="overview">{t('tabs.overview')}</TabsTrigger>
        <TabsTrigger value="metadata">{t('tabs.metadata')}</TabsTrigger>
        {showData && <TabsTrigger value="data">{t('tabs.data')}</TabsTrigger>}
        {showStructure && <TabsTrigger value="structure">{t('tabs.structure')}</TabsTrigger>}
        {showSources && <TabsTrigger value="sources">{t('tabs.sources')}</TabsTrigger>}
        {/* Members tab hidden until collection membership is implemented */}
        <TabsTrigger value="access">{t('tabs.access')}</TabsTrigger>
      </TabsList>

      <TabsContent value="overview" className="space-y-6">
        <OverviewTab
          dataset={dataset}
          canEdit={canEdit}
          capabilities={capabilities}
          summaryValue={resolveDraftValue('summary')}
          onSummaryDraftSave={(value) => stagePendingDraft('summary', value)}
          onSummaryDirtyChange={(isDirty) => handleDraftDirtyChange('summary', isDirty)}
          datasetId={dataset.id}
        />
      </TabsContent>

      <TabsContent value="metadata" className="space-y-6">
        <MetadataTab
          dataset={dataset}
          canEdit={canEdit}
          capabilities={capabilities}
          draftValues={draftValues}
          onDraftSave={stagePendingDraft}
          onDraftDirtyChange={handleDraftDirtyChange}
          onNavigateToValidationField={onNavigateToValidationField}
        />
      </TabsContent>

      {showData && (
        <TabsContent value="data" className="space-y-6">
          <DataTab
            datasetId={dataset.id}
            canEdit={canEdit}
            expanded={isTableExpanded}
            onToggleExpand={onToggleTableExpand}
          />
        </TabsContent>
      )}

      {showStructure && (
        <TabsContent value="structure" className="space-y-6">
          <StructureTab
            datasetId={dataset.id}
            canEdit={canEdit}
            columnInfo={dataset.column_info}
            capability={capabilities.theme_category}
            tableName={dataset.table_name}
          />
        </TabsContent>
      )}

      {showSources && (
        <TabsContent value="sources" className="space-y-6">
          <SourcesTab dataset={dataset} canEdit={canEdit} datasetId={dataset.id} />
        </TabsContent>
      )}

      <TabsContent value="access" className="space-y-6">
        <AccessTab dataset={dataset} datasetId={dataset.id} />
      </TabsContent>
    </Tabs>
  );
}
