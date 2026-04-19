import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Settings } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AttributeMetadataTable } from '@/components/dataset/AttributeMetadataTable';
import { SchemaEditor } from '@/components/dataset/SchemaEditor';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import type { DatasetEditCapability } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

interface StructureTabProps {
  datasetId: string;
  canEdit: boolean;
  columnInfo?: { name: string; type: string }[] | null;
  capability: DatasetEditCapability;
}

export function StructureTab({ datasetId, canEdit, columnInfo, capability }: StructureTabProps) {
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
