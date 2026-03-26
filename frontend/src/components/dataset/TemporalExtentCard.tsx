import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useUpdateDataset } from '@/hooks/use-dataset';
import type { DatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import { formatDate } from '@/lib/format';

interface TemporalExtentCardProps {
  datasetId: string;
  dataVintageStart: string | null;
  dataVintageEnd: string | null;
  capabilities: DatasetEditCapabilities;
}

export function TemporalExtentCard({
  datasetId,
  dataVintageStart,
  dataVintageEnd,
  capabilities,
}: TemporalExtentCardProps) {
  const { t } = useTranslation('dataset');
  const updateDataset = useUpdateDataset();

  const handleSaveVintageStart = useCallback(
    async (value: string) => {
      await updateDataset.mutateAsync({
        datasetId,
        data: { data_vintage_start: value || undefined },
      });
    },
    [datasetId, updateDataset],
  );

  const handleSaveVintageEnd = useCallback(
    async (value: string) => {
      await updateDataset.mutateAsync({
        datasetId,
        data: { data_vintage_end: value || undefined },
      });
    },
    [datasetId, updateDataset],
  );

  return (
    <Card data-field-anchor="temporal_extent">
      <CardHeader>
        <CardTitle className="text-base">{t('metadata.temporalExtent')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <SectionCapabilityHint capability={capabilities.data_vintage_start} />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1">
            <span className="text-sm font-medium text-muted-foreground">
              {t('metadataEdit.vintageStart')}
            </span>
            <EditableFieldShell capability={capabilities.data_vintage_start} testId="editable-field-shell-vintage-start">
              <InlineEdit
                value={dataVintageStart ? formatDate(dataVintageStart) : ''}
                onSave={handleSaveVintageStart}
                as="p"
                canEdit={capabilities.data_vintage_start.editable}
                placeholder={t('metadata.noTemporalExtent')}
                className="text-sm"
              />
            </EditableFieldShell>
          </div>
          <div className="space-y-1">
            <span className="text-sm font-medium text-muted-foreground">
              {t('metadataEdit.vintageEnd')}
            </span>
            <EditableFieldShell capability={capabilities.data_vintage_end} testId="editable-field-shell-vintage-end">
              <InlineEdit
                value={dataVintageEnd ? formatDate(dataVintageEnd) : ''}
                onSave={handleSaveVintageEnd}
                as="p"
                canEdit={capabilities.data_vintage_end.editable}
                placeholder={t('metadata.noTemporalExtent')}
                className="text-sm"
              />
            </EditableFieldShell>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
