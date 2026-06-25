import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Settings } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AttributeMetadataTable } from '@/components/dataset/AttributeMetadataTable';
import { SchemaEditor } from '@/components/dataset/SchemaEditor';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import { RoleCapabilityHint } from '@/components/dataset/RoleCapabilityHint';
import type { DatasetEditCapability } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

interface StructureTabProps {
  datasetId: string;
  canEdit: boolean;
  columnInfo?: { name: string; type: string }[] | null;
  capability: DatasetEditCapability;
  /** True when the user owns/admins this dataset but attribute editing is
   *  disabled by deployment config (enable_dataset_editing=false) — so we can
   *  explain the absence of edit controls instead of showing nothing. */
  gatedByDeployment?: boolean;
}

export function StructureTab({ datasetId, canEdit, columnInfo, capability, gatedByDeployment }: StructureTabProps) {
  const { t } = useTranslation('dataset');
  const [schemaOpen, setSchemaOpen] = useState(false);

  return (
    <>
      {/* Attribute Metadata */}
      <Card data-field-anchor="attribute_metadata">
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">{t('attributeMetadata.title')}</CardTitle>
          {canEdit && columnInfo && capability.editable && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSchemaOpen(true)}
            >
              <Settings className="h-4 w-4 me-1" />
              {t('metadata.manageColumns')}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {canEdit && <SectionCapabilityHint capability={capability} />}
          {!canEdit && gatedByDeployment && (
            <RoleCapabilityHint
              reason="read_only_field"
              helper={t('attributeMetadata.editingDisabled', {
                defaultValue: 'Attribute editing is disabled for this deployment.',
              })}
            />
          )}
          <AttributeMetadataTable datasetId={datasetId} canEdit={canEdit && capability.editable} />
        </CardContent>
      </Card>

      {/* Schema Editor Dialog */}
      {canEdit && columnInfo && capability.editable && (
        <SchemaEditor
          datasetId={datasetId}
          columns={columnInfo}
          open={schemaOpen}
          onOpenChange={setSchemaOpen}
        />
      )}
    </>
  );
}
