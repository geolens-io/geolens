import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useAttributes } from '@/components/dataset/hooks/use-dataset';
import { valueLabelsByField } from '@/lib/value-labels';
import { Maximize2, Minimize2, AlignJustify, List } from 'lucide-react';

interface DataTabProps {
  datasetId: string;
  canEdit: boolean;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

/**
 * Document offset of the element's top edge. Banners, previews and wrapped
 * titles above the tab move it, so it is re-read whenever the body resizes.
 */
function useDocumentTop(ref: React.RefObject<HTMLElement | null>): number | null {
  const [top, setTop] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setTop(Math.round(el.getBoundingClientRect().top + window.scrollY));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(document.body);
    return () => observer.disconnect();
  }, [ref]);
  return top;
}

export function DataTab({ datasetId, canEdit, expanded = false, onToggleExpand }: DataTabProps) {
  const { t } = useTranslation('dataset');
  const [compact, setCompact] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const top = useDocumentTop(rootRef);
  const { data: attributeList } = useAttributes(datasetId);
  const valueLabels = useMemo(
    () => valueLabelsByField(attributeList?.attributes),
    [attributeList],
  );

  const actions = (
    <>
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
    </>
  );

  // The tab takes the viewport height left below it at the top of the page,
  // so the table box and its pagination fit without page scroll; the
  // expanded view fills that height. A floating launcher such as Ask AI
  // publishes the bottom space it covers as --floating-dock-inset. The floor
  // keeps a usable table on short viewports.
  const fill = top == null
    ? undefined
    : `max(20rem, calc(100dvh - ${top}px - var(--floating-dock-inset, 1rem)))`;
  return (
    <div
      ref={rootRef}
      className="flex flex-col"
      style={expanded ? { height: fill } : { maxHeight: fill }}
    >
      <AttributeTable
        datasetId={datasetId}
        canEdit={canEdit}
        compact={compact}
        valueLabels={valueLabels}
        heading={
          <span role="heading" aria-level={2} className="text-sm font-medium">
            {t('page.attributeData')}
          </span>
        }
        actions={actions}
      />
    </div>
  );
}
