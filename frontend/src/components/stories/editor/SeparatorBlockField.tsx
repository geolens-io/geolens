import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { SeparatorStyle } from '@/components/widgets/separator/definition';
import type { StoryChapter } from '@/types/api';
import type { DraftEdit } from './story-draft';

type SeparatorBlock = Extract<NonNullable<StoryChapter['blocks']>[number], { type: 'separator' }>;

interface SeparatorBlockFieldProps {
  chapterId: string;
  block: SeparatorBlock;
  label: string;
  edit: (change: DraftEdit) => void;
}

const STYLES: readonly SeparatorStyle[] = ['line', 'gap'];

/** A separator block: a thin line, or a larger gap. */
export function SeparatorBlockField({ chapterId, block, label, edit }: SeparatorBlockFieldProps) {
  const { t } = useTranslation('stories');
  const labelId = useId();
  return (
    <fieldset className="space-y-2 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <span id={labelId} className="text-sm">
        {t('editor.separator.style')}
      </span>
      <div>
        <ToggleGroup
          type="single"
          aria-labelledby={labelId}
          value={block.config.style}
          // Clicking the chosen style again reports an empty value; one stays chosen.
          onValueChange={(style) =>
            style && edit({ type: 'setSeparator', chapterId, blockId: block.id, style: style as SeparatorStyle })
          }
        >
          {STYLES.map((style) => (
            <ToggleGroupItem key={style} value={style}>
              {t(`editor.separator.${style}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
    </fieldset>
  );
}
