import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { DatasetResponse } from '@/types/api';
import type { DatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import type { PendingDraftField } from '@/components/dataset/hooks/use-draft-editing';
import type { DatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { OverviewTab } from '../tabs/OverviewTab';
import { MetadataTab } from '../tabs/MetadataTab';
import { DataTab } from '../tabs/DataTab';
import { StructureTab } from '../tabs/StructureTab';
import { SourcePanel } from '../SourcePanel';
import { REFRESHABLE_ORIGINS, SourceRefreshAction } from '../SourceRefreshAction';
import { datasetOrigin } from '../OriginBadge';
import { AccessTab } from '../tabs/AccessTab';

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
  /**
   * fix(#1285 codex round 4): owned by the dataset page (useDatasetRefreshWatch)
   * rather than by SourceRefreshAction itself, because the "sources" tab
   * content unmounts on tab switch (Radix Tabs) and would otherwise drop a
   * dispatched run's tracking mid-poll. Required — the only real caller
   * (DatasetPage) always has one; tests that stub SourcePanel out entirely
   * pass a static one.
   */
  refreshWatch: DatasetRefreshWatch;
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
    refreshWatch,
  } = props;

  const recordType = dataset.record_type;
  const isTable = recordType === 'table';
  const isVector = recordType === 'vector_dataset' || isTable || !recordType;

  // fix(#1285 codex round 1): origin PRESENCE isn't the refresh door's gate —
  // `dataset.origin` is the server-computed field (datasetOrigin() is the
  // client-side fallback for older payloads that predate it), but an upload,
  // created, or STAC origin is just as resolvable as a service or postgis
  // one and the endpoint refuses all three with 409 refresh_not_applicable.
  // REFRESHABLE_ORIGINS is the one place that actually mirrors the backend's
  // dispatch table.
  const origin = dataset.origin ?? datasetOrigin(dataset);
  const canRefresh = origin != null && REFRESHABLE_ORIGINS.has(origin);

  const showData = isVector;
  const showStructure = isVector;

  // fix(#649): a deep link can leave activeTab pointing at a tab whose
  // trigger/content are hidden (for example ?tab=data on a raster); Radix
  // controlled tabs then render nothing below the tab list. Clamp to Overview
  // whenever the selected tab isn't visible.
  const hiddenTabs = {
    data: !showData,
    structure: !showStructure,
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
    attribution: resolveDraftValue('attribution'),
  }), [resolveDraftValue]);

  return (
    <Tabs value={effectiveTab} onValueChange={onTabChange}>
      <TabsList className="w-full sticky top-0 z-20 bg-background border-b">
        <TabsTrigger value="overview">{t('tabs.overview')}</TabsTrigger>
        <TabsTrigger value="metadata">{t('tabs.metadata')}</TabsTrigger>
        {showData && <TabsTrigger value="data">{t('tabs.data')}</TabsTrigger>}
        {showStructure && <TabsTrigger value="structure">{t('tabs.structure')}</TabsTrigger>}
        <TabsTrigger value="sources">{t('tabs.sources')}</TabsTrigger>
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

      <TabsContent value="sources" className="space-y-6">
        <SourcePanel
          dataset={dataset}
          canEdit={canEdit}
          actions={
            canEdit && canRefresh
              ? <SourceRefreshAction dataset={dataset} watch={refreshWatch} />
              : undefined
          }
        />
      </TabsContent>

      <TabsContent value="access" className="space-y-6">
        <AccessTab dataset={dataset} canEdit={canEdit} />
      </TabsContent>
    </Tabs>
  );
}
