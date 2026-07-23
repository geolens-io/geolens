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
import { useAuthStore } from '@/stores/auth-store';

export interface DetailPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  /** Gates geometry/attribute cell editing (feature-flagged separately from metadata editing). */
  canEditData?: boolean;
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
    canEditData = canEdit,
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

  const showData = isVector;
  const showStructure = isVector;
  // fix(#644): SourcesTab's queries need an authenticated user (the VRT GET
  // routes visibility-check but reject anonymous), so showing the tab to
  // anonymous viewers could only ever render 401 noise. Signed-in non-owners
  // keep the read-only view (codex P2 on #649); mutation controls inside the
  // tab stay gated by canEdit.
  const isAuthenticated = useAuthStore((s) => !!s.token);
  const showSources = isVrt && isAuthenticated;

  // fix(#649 codex r2): a deep link or sign-out can leave activeTab pointing
  // at a tab whose trigger/content are hidden (anonymous + #sources, ?tab=data
  // on a raster, …); Radix controlled tabs then render nothing below the tab
  // list. Clamp to Overview whenever the selected tab isn't visible.
  const hiddenTabs = {
    data: !showData,
    structure: !showStructure,
    sources: !showSources,
  } as const;
  const effectiveTab =
    hiddenTabs[activeTab as keyof typeof hiddenTabs] ? 'overview' : activeTab;

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
    <Tabs value={effectiveTab} onValueChange={onTabChange}>
      <TabsList className="w-full sticky top-0 z-20 bg-background border-b">
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
          onTabChange={onTabChange}
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
            canEdit={canEditData}
            expanded={isTableExpanded}
            onToggleExpand={onToggleTableExpand}
          />
        </TabsContent>
      )}

      {showStructure && (
        <TabsContent value="structure" className="space-y-6">
          <StructureTab
            datasetId={dataset.id}
            canEdit={canEditData}
            columnInfo={dataset.column_info}
            capability={capabilities.theme_category}
            gatedByDeployment={canEdit && !canEditData}
          />
        </TabsContent>
      )}

      {showSources && (
        <TabsContent value="sources" className="space-y-6">
          <SourcesTab dataset={dataset} canEdit={canEdit} datasetId={dataset.id} />
        </TabsContent>
      )}

      <TabsContent value="access" className="space-y-6">
        <AccessTab dataset={dataset} />
      </TabsContent>
    </Tabs>
  );
}
