import { useState } from 'react';
import { useTranslation } from 'react-i18next';
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

  const toolbar = (
    <div className="flex items-center justify-between py-1.5 shrink-0">
      <span className="text-sm font-medium">{t('page.attributeData')}</span>
      <div className="flex items-center gap-1">
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
        {onToggleExpand && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={onToggleExpand}
            aria-label={expanded ? t('data.collapseTable') : t('data.expandTable')}
          >
            {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <div className={expanded ? 'flex flex-col h-[calc(100vh-10rem)]' : undefined}>
      {toolbar}
      <div className={expanded ? 'flex-1 overflow-y-auto min-h-0' : undefined}>
        <AttributeTable datasetId={datasetId} canEdit={canEdit} compact={compact} />
      </div>
    </div>
  );
}
