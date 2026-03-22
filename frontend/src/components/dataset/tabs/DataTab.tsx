import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AttributeTable } from '@/components/dataset/AttributeTable';

interface DataTabProps {
  datasetId: string;
  canEdit: boolean;
}

export function DataTab({ datasetId, canEdit }: DataTabProps) {
  const { t } = useTranslation('dataset');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('page.attributeData')}</CardTitle>
      </CardHeader>
      <CardContent>
        <AttributeTable datasetId={datasetId} canEdit={canEdit} />
      </CardContent>
    </Card>
  );
}
