import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Settings } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CopyButton } from '@/components/ui/copy-button';
import { AttributeMetadataTable } from '@/components/dataset/AttributeMetadataTable';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { SchemaEditor } from '@/components/dataset/SchemaEditor';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import type { DatasetEditCapability } from '@/hooks/use-dataset-edit-capabilities';

interface StructureTabProps {
  datasetId: string;
  canEdit: boolean;
  columnInfo?: { name: string; type: string }[] | null;
  capability: DatasetEditCapability;
  tableName?: string;
  recordType?: string;
}

export function StructureTab({ datasetId, canEdit, columnInfo, capability, tableName, recordType }: StructureTabProps) {
  const { t } = useTranslation('dataset');
  const [schemaOpen, setSchemaOpen] = useState(false);

  return (
    <>
      {/* Table Name */}
      {tableName && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t('metadata.tableName', { defaultValue: 'Table:' })}</span>
          <code className="font-mono text-xs bg-muted px-2 py-1 rounded">{tableName}</code>
          <CopyButton value={tableName} />
        </div>
      )}

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
              <Settings className="h-4 w-4 mr-1" />
              {t('metadata.manageColumns')}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <SectionCapabilityHint capability={capability} />
          <EditableFieldShell capability={capability} testId="editable-field-shell-structure">
            <AttributeMetadataTable datasetId={datasetId} canEdit={canEdit && capability.editable} />
          </EditableFieldShell>
        </CardContent>
      </Card>

      {/* Data Preview (hidden for table datasets — hero grid already shows it) */}
      {recordType !== 'table' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('page.attributeData')}</CardTitle>
          </CardHeader>
          <CardContent>
            <AttributeTable datasetId={datasetId} />
          </CardContent>
        </Card>
      )}

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
