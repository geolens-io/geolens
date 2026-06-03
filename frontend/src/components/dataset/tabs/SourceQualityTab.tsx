import { useState, useCallback, useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse } from '@/types/api';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useLineageDraft, useQualityStatementDraft } from '@/hooks/use-ai-metadata';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { AiAssistButton, AiDraftPreview } from '@/components/dataset/AiAssistButton';
import { QualityScoreCard } from '@/components/dataset/QualityScoreCard';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import { SpatialExtentCard } from '@/components/dataset/SpatialExtentCard';
import { TemporalExtentCard } from '@/components/dataset/TemporalExtentCard';
import type { DatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { UPDATE_FREQUENCY_OPTIONS, SENSITIVITY_OPTIONS, THEME_CATEGORIES } from '@/lib/iso-constants';

interface SourceQualityTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  datasetId: string;
  capabilities: DatasetEditCapabilities;
  draftValues: SourceQualityDraftValues;
  onDraftSave: (field: SourceQualityDraftField, value: string) => void;
  onDraftDirtyChange: (field: SourceQualityDraftField, isDirty: boolean) => void;
}

export type SourceQualityDraftField =
  | 'lineage_summary'
  | 'source_url'
  | 'source_organization'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement';

export type SourceQualityDraftValues = Record<SourceQualityDraftField, string>;

function translateUpdateFrequency(
  t: (key: string, options?: Record<string, unknown>) => string,
  value: string,
): string {
  return t(`iso.updateFrequencyOptions.${value}`, { defaultValue: value });
}

function translateSensitivity(
  t: (key: string, options?: Record<string, unknown>) => string,
  value: string,
): string {
  return t(`iso.sensitivityOptions.${value}`, { defaultValue: value });
}

function translateThemeCategory(
  t: (key: string, options?: Record<string, unknown>) => string,
  value: string,
): string {
  return t(`iso.themeCategories.${value}`, { defaultValue: value });
}


export function SourceQualityTab({
  dataset,
  canEdit,
  datasetId,
  capabilities,
  draftValues,
  onDraftSave,
  onDraftDirtyChange,
}: SourceQualityTabProps) {
  const { t } = useTranslation('dataset');
  const { isAIAvailable } = useAIAvailability();
  const lineageDraft = useLineageDraft();
  const [lineageDraftText, setLineageDraftText] = useState<string | null>(null);
  const qualityStatementDraft = useQualityStatementDraft();
  const [qualityDraftText, setQualityDraftText] = useState<string | null>(null);
  const updateDataset = useUpdateDataset();
  const [expandedFields, setExpandedFields] = useState<Set<string>>(() => new Set());

  const toggleExpanded = useCallback((field: string) => {
    setExpandedFields((prev) => {
      const next = new Set(prev);
      next.add(field);
      return next;
    });
  }, []);

  /** Renders a compact empty state when value is empty and field is editable */
  const renderReadFirstField = (
    fieldName: string,
    value: string,
    editable: boolean,
    children: ReactNode,
    label: string,
  ) => {
    if (!value && editable && !expandedFields.has(fieldName)) {
      return (
        <button
          type="button"
          className="text-sm text-muted-foreground italic hover:text-foreground transition-colors"
          onClick={() => toggleExpanded(fieldName)}
        >
          {t('inline.clickToAdd', { defaultValue: 'Click to add {{field}}', field: label.toLowerCase() })}
        </button>
      );
    }
    if (!value && !editable) {
      return <p className="text-sm text-muted-foreground italic">{t('common:notSet', { defaultValue: 'Not set' })}</p>;
    }
    return children;
  };

  const selectedCategories = useMemo(() => dataset.theme_category ?? [], [dataset.theme_category]);

  const handleFrequencyChange = useCallback(
    (value: string) => {
      onDraftSave('update_frequency', value);
      toast.success(
        t('affordances.pending.fieldStaged', {
          defaultValue: 'Change added to pending edits.',
        }),
      );
    },
    [onDraftSave, t],
  );

  const handleSensitivityChange = useCallback(
    (value: string) => {
      onDraftSave('sensitivity_classification', value);
      toast.success(
        t('affordances.pending.fieldStaged', {
          defaultValue: 'Change added to pending edits.',
        }),
      );
    },
    [onDraftSave, t],
  );

  const handleThemeCategoryToggle = useCallback(
    async (category: string, checked: boolean) => {
      const updated = checked
        ? [...selectedCategories, category]
        : selectedCategories.filter((c) => c !== category);

      try {
        await updateDataset.mutateAsync({
          datasetId,
          data: { theme_category: updated },
        });
        toast.success(t('iso.themeCategoryUpdated'));
      } catch {
        toast.error(t('iso.themeCategoryUpdateFailed'));
      }
    },
    [datasetId, selectedCategories, t, updateDataset],
  );

  return (
    <>
      <SpatialExtentCard
        extentBbox={dataset.extent_bbox}
        srid={dataset.srid}
        originalSrid={dataset.original_srid}
      />

      <TemporalExtentCard
        datasetId={datasetId}
        dataVintageStart={dataset.data_vintage_start}
        dataVintageEnd={dataset.data_vintage_end}
        capabilities={capabilities}
      />

      {/* Source Information */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('sections.sourceInformation')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SectionCapabilityHint capability={capabilities.lineage_summary} />

          <div className="space-y-1" data-field-anchor="lineage_summary">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium text-muted-foreground">
                {t('iso.lineage')}
              </Label>
              {canEdit && isAIAvailable && (
                <AiAssistButton
                  onClick={() =>
                    lineageDraft
                      .mutateAsync(datasetId)
                      .then((r) => setLineageDraftText(r.draft))
                      .catch(() => toast.error(t('ai.lineageFailed')))
                  }
                  isPending={lineageDraft.isPending}
                  label={t('ai.draftLineage', { defaultValue: 'Draft lineage' })}
                />
              )}
            </div>
            {renderReadFirstField('lineage_summary', draftValues.lineage_summary, capabilities.lineage_summary.editable, (
              <EditableFieldShell capability={capabilities.lineage_summary} testId="editable-field-shell-lineage-summary">
                <InlineEdit
                  value={draftValues.lineage_summary}
                  onSave={(val) => onDraftSave('lineage_summary', val)}
                  as="p"
                  multiline
                  canEdit={capabilities.lineage_summary.editable}
                  placeholder={t('iso.lineagePlaceholder')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('lineage_summary', isDirty)}
                />
              </EditableFieldShell>
            ), t('iso.lineage'))}
            {lineageDraftText !== null && (
              <AiDraftPreview
                draft={lineageDraftText}
                onAccept={async (editedText) => {
                  await onDraftSave('lineage_summary', editedText);
                  setLineageDraftText(null);
                  toast.success(
                    t('affordances.pending.fieldStaged', {
                      defaultValue: 'Change added to pending edits.',
                    }),
                  );
                }}
                onDiscard={() => setLineageDraftText(null)}
              />
            )}
          </div>

          <div className="space-y-1" data-field-anchor="source_url">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('iso.sourceUrl')}
            </Label>
            {renderReadFirstField('source_url', draftValues.source_url, capabilities.source_url.editable, (
              <EditableFieldShell capability={capabilities.source_url} testId="editable-field-shell-source-url">
                <InlineEdit
                  value={draftValues.source_url}
                  onSave={(val) => onDraftSave('source_url', val)}
                  as="p"
                  canEdit={capabilities.source_url.editable}
                  placeholder={t('iso.sourceUrlPlaceholder')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('source_url', isDirty)}
                />
              </EditableFieldShell>
            ), t('iso.sourceUrl'))}
          </div>

          <div className="space-y-1" data-field-anchor="source_organization">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('metadata.sourceOrganization')}
            </Label>
            {renderReadFirstField('source_organization', draftValues.source_organization, capabilities.source_organization.editable, (
              <EditableFieldShell capability={capabilities.source_organization} testId="editable-field-shell-source-organization">
                <InlineEdit
                  value={draftValues.source_organization}
                  onSave={(val) => onDraftSave('source_organization', val)}
                  as="p"
                  canEdit={capabilities.source_organization.editable}
                  placeholder={t('metadata.sourceOrganization')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('source_organization', isDirty)}
                />
              </EditableFieldShell>
            ), t('metadata.sourceOrganization'))}
          </div>

          <div className="space-y-1" data-field-anchor="update_frequency">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('iso.updateFrequency')}
            </Label>
            <EditableFieldShell capability={capabilities.update_frequency} testId="editable-field-shell-update-frequency">
              {capabilities.update_frequency.editable ? (
                <Select
                  value={draftValues.update_frequency || undefined}
                  onValueChange={handleFrequencyChange}
                >
                  <SelectTrigger className="h-8 w-56">
                    <SelectValue placeholder={t('iso.updateFrequency')} />
                  </SelectTrigger>
                  <SelectContent>
                    {UPDATE_FREQUENCY_OPTIONS.map((opt) => (
                      <SelectItem key={opt} value={opt}>
                        {translateUpdateFrequency(t, opt)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm">
                  {draftValues.update_frequency
                    ? translateUpdateFrequency(t, draftValues.update_frequency)
                    : t('common:notAvailable')}
                </p>
              )}
            </EditableFieldShell>
          </div>
        </CardContent>
      </Card>

      {/* Quality */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('sections.quality')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SectionCapabilityHint capability={capabilities.quality_statement} />

          <div className="space-y-1" data-field-anchor="quality_statement">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium text-muted-foreground">
                {t('iso.qualityStatement')}
              </Label>
              {canEdit && isAIAvailable && (
                <AiAssistButton
                  onClick={() =>
                    qualityStatementDraft
                      .mutateAsync(datasetId)
                      .then((r) => setQualityDraftText(r.draft))
                      .catch(() => toast.error(t('ai.qualityStatementFailed')))
                  }
                  isPending={qualityStatementDraft.isPending}
                  label={t('ai.draftQualityStatement', { defaultValue: 'Draft quality statement' })}
                />
              )}
            </div>
            {renderReadFirstField('quality_statement', draftValues.quality_statement, capabilities.quality_statement.editable, (
              <EditableFieldShell capability={capabilities.quality_statement} testId="editable-field-shell-quality-statement">
                <InlineEdit
                  value={draftValues.quality_statement}
                  onSave={(val) => onDraftSave('quality_statement', val)}
                  as="p"
                  multiline
                  canEdit={capabilities.quality_statement.editable}
                  placeholder={t('iso.qualityStatementPlaceholder')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('quality_statement', isDirty)}
                />
              </EditableFieldShell>
            ), t('iso.qualityStatement'))}
            {qualityDraftText !== null && (
              <AiDraftPreview
                draft={qualityDraftText}
                onAccept={async (editedText) => {
                  await onDraftSave('quality_statement', editedText);
                  setQualityDraftText(null);
                  toast.success(
                    t('affordances.pending.fieldStaged', {
                      defaultValue: 'Change added to pending edits.',
                    }),
                  );
                }}
                onDiscard={() => setQualityDraftText(null)}
              />
            )}
          </div>
        </CardContent>
      </Card>

      {/* Quality Score */}
      <QualityScoreCard qualityScore={dataset.quality_detail} updateFrequency={dataset.update_frequency} />

      {/* Theme Category */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('iso.themeCategory')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <SectionCapabilityHint capability={capabilities.theme_category} />
          <EditableFieldShell capability={capabilities.theme_category} testId="editable-field-shell-theme-category">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {THEME_CATEGORIES.map((category) => {
                const isChecked = selectedCategories.includes(category);
                return (
                  <div key={category} className="flex items-center gap-2">
                    <Checkbox
                      id={`theme-${category}`}
                      checked={isChecked}
                      onCheckedChange={(checked) =>
                        canEdit && handleThemeCategoryToggle(category, checked === true)
                      }
                      disabled={!capabilities.theme_category.editable}
                    />
                    <Label
                      htmlFor={`theme-${category}`}
                      className="text-sm font-normal cursor-pointer"
                    >
                      {translateThemeCategory(t, category)}
                    </Label>
                  </div>
                );
              })}
            </div>
          </EditableFieldShell>
        </CardContent>
      </Card>

      {/* Governance */}
      <Card data-field-anchor="governance">
        <CardHeader>
          <CardTitle className="text-base">{t('sections.governance')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SectionCapabilityHint capability={capabilities.usage_constraints} />

          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('iso.usageConstraints')}
            </Label>
            {renderReadFirstField('usage_constraints', draftValues.usage_constraints, capabilities.usage_constraints.editable, (
              <EditableFieldShell capability={capabilities.usage_constraints} testId="editable-field-shell-usage-constraints">
                <InlineEdit
                  value={draftValues.usage_constraints}
                  onSave={(val) => onDraftSave('usage_constraints', val)}
                  as="p"
                  multiline
                  canEdit={capabilities.usage_constraints.editable}
                  placeholder={t('iso.usageConstraintsPlaceholder')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('usage_constraints', isDirty)}
                />
              </EditableFieldShell>
            ), t('iso.usageConstraints'))}
          </div>

          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('iso.accessConstraints')}
            </Label>
            {renderReadFirstField('access_constraints', draftValues.access_constraints, capabilities.access_constraints.editable, (
              <EditableFieldShell capability={capabilities.access_constraints} testId="editable-field-shell-access-constraints">
                <InlineEdit
                  value={draftValues.access_constraints}
                  onSave={(val) => onDraftSave('access_constraints', val)}
                  as="p"
                  multiline
                  canEdit={capabilities.access_constraints.editable}
                  placeholder={t('iso.accessConstraintsPlaceholder')}
                  className="text-sm"
                  onDirtyChange={(isDirty) => onDraftDirtyChange('access_constraints', isDirty)}
                />
              </EditableFieldShell>
            ), t('iso.accessConstraints'))}
          </div>

          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              {t('iso.sensitivity')}
            </Label>
            <EditableFieldShell capability={capabilities.sensitivity_classification} testId="editable-field-shell-sensitivity">
              {capabilities.sensitivity_classification.editable ? (
                <Select
                  value={draftValues.sensitivity_classification || undefined}
                  onValueChange={handleSensitivityChange}
                >
                  <SelectTrigger className="h-8 w-56">
                    <SelectValue placeholder={t('iso.sensitivity')} />
                  </SelectTrigger>
                  <SelectContent>
                    {SENSITIVITY_OPTIONS.map((opt) => (
                      <SelectItem key={opt} value={opt}>
                        {translateSensitivity(t, opt)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm">
                  {draftValues.sensitivity_classification
                    ? translateSensitivity(t, draftValues.sensitivity_classification)
                    : t('common:notAvailable')}
                </p>
              )}
            </EditableFieldShell>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
