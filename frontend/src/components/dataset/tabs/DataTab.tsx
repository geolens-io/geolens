import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { Maximize2, Minimize2, AlignJustify, List } from 'lucide-react';

interface DataTabProps {
  datasetId: string;
  canEdit: boolean;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function DataTab({ datasetId, canEdit, expanded = false, onToggleExpand }: DataTabProps) {
  const { t } = useTranslation('dataset');
  const [compact, setCompact] = useState(false);

  const densityToggle = (
    <Button
      variant="ghost"
      size="sm"
      className="h-7 w-7 p-0"
      onClick={() => setCompact((v) => !v)}
      aria-label={compact ? t('data.switchComfortable') : t('data.switchCompact')}
      title={compact ? t('data.comfortable') : t('data.compact')}
    >
      {compact ? <AlignJustify className="h-4 w-4" /> : <List className="h-4 w-4" />}
    </Button>
  );

  if (expanded) {
    return (
      <div className="flex flex-col h-[calc(100vh-10rem)]">
        <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/30 shrink-0">
          <span className="text-sm font-medium">{t('page.attributeData')}</span>
          <div className="flex items-center gap-2">
            {densityToggle}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={onToggleExpand}
              aria-label={t('data.collapseTable')}
            >
              <Minimize2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto min-h-0 p-4">
          <AttributeTable datasetId={datasetId} canEdit={canEdit} compact={compact} />
        </div>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">{t('page.attributeData')}</CardTitle>
        <div className="flex items-center gap-1">
          {densityToggle}
          {onToggleExpand && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={onToggleExpand}
              aria-label={t('data.expandTable')}
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <AttributeTable datasetId={datasetId} canEdit={canEdit} compact={compact} />
      </CardContent>
    </Card>
  );
}
