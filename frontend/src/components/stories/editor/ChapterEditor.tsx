import { useEffect, useId, useRef } from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { randomId } from '@/lib/random-id';
import type { StoryCamera, StoryChapter } from '@/types/api';
import { ButtonBlockField } from './ButtonBlockField';
import { ImageBlockField } from './ImageBlockField';
import { MarkdownField } from './MarkdownField';
import { SceneEditor } from './SceneEditor';
import { SeparatorBlockField } from './SeparatorBlockField';
import { CHAPTER_TITLE_MAX_LENGTH, MAX_BLOCKS_PER_CHAPTER, type DraftEdit } from './story-draft';
import { StoryImagePicker } from './StoryImagePicker';
import { useMoveFocus } from './use-move-focus';
import type { StoryUploads } from './use-story-uploads';

const MOVES = [
  {
    by: -1,
    Icon: ArrowUp,
    label: {
      image: 'editor.chapter.moveImageUp',
      markdown: 'editor.chapter.moveTextBlockUp',
      button: 'editor.chapter.moveButtonUp',
      separator: 'editor.chapter.moveSeparatorUp',
    },
  },
  {
    by: 1,
    Icon: ArrowDown,
    label: {
      image: 'editor.chapter.moveImageDown',
      markdown: 'editor.chapter.moveTextBlockDown',
      button: 'editor.chapter.moveButtonDown',
      separator: 'editor.chapter.moveSeparatorDown',
    },
  },
] as const;

const ADD_BLOCKS = [
  { type: 'addTextBlock', label: 'editor.chapter.addTextBlock' },
  { type: 'addButtonBlock', label: 'editor.chapter.addButton' },
  { type: 'addSeparatorBlock', label: 'editor.chapter.addSeparator' },
] as const;

const REMOVE_LABELS = {
  image: 'editor.chapter.removeImage',
  markdown: 'editor.chapter.removeBlock',
  button: 'editor.chapter.removeButton',
  separator: 'editor.chapter.removeSeparator',
} as const;

interface ChapterEditorProps {
  storyId: string;
  uploads: StoryUploads;
  chapter: StoryChapter;
  index: number;
  edit: (change: DraftEdit) => void;
  readView: () => StoryCamera | null;
  mapMissing: boolean;
  /** Focus the title on mount, for a chapter just added. */
  focusTitle: boolean;
}

/** One chapter's title, scene, and text and image blocks. */
export function ChapterEditor({
  storyId,
  uploads,
  chapter,
  index,
  edit,
  readView,
  mapMissing,
  focusTitle,
}: ChapterEditorProps) {
  const { t } = useTranslation('stories');
  const titleId = useId();
  const titleRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLElement>(null);
  const blocks = chapter.blocks ?? [];
  const blocksFull = blocks.length >= MAX_BLOCKS_PER_CHAPTER;
  const kindCounts = new Map<string, number>();
  const kindNumbers = blocks.map((block) => {
    const n = (kindCounts.get(block.type) ?? 0) + 1;
    kindCounts.set(block.type, n);
    return n;
  });

  useEffect(() => {
    if (focusTitle) titleRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a newly mounted chapter takes focus
  }, []);

  const markMoved = useMoveFocus(textRef, 'data-block-id', chapter.blocks);

  const addButton = ({ type, label }: (typeof ADD_BLOCKS)[number]) => (
    <Button
      key={type}
      type="button"
      variant="outline"
      size="sm"
      disabled={blocksFull}
      aria-describedby={blocksFull ? `${titleId}-blocks-full` : undefined}
      onClick={() => edit({ type, chapterId: chapter.id, blockId: randomId() })}
    >
      <Plus className="h-4 w-4" aria-hidden="true" />
      {t(label)}
    </Button>
  );

  function moveBlock(blockId: string, by: -1 | 1) {
    markMoved(blockId, by);
    edit({ type: 'moveBlock', chapterId: chapter.id, blockId, by });
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Label htmlFor={titleId}>{t('editor.chapter.title')}</Label>
        <Input
          ref={titleRef}
          id={titleId}
          value={chapter.title ?? ''}
          maxLength={CHAPTER_TITLE_MAX_LENGTH}
          placeholder={t('reader.untitledChapter', { index: index + 1 })}
          onChange={(event) => edit({ type: 'setTitle', chapterId: chapter.id, title: event.target.value })}
        />
      </div>

      <section aria-labelledby={`${titleId}-scene`} className="space-y-2">
        <h3 id={`${titleId}-scene`} className="text-sm font-semibold">
          {t('editor.scene.heading')}
        </h3>
        <SceneEditor
          chapterId={chapter.id}
          scene={chapter.scene ?? null}
          sceneHidden={chapter.scene_hidden}
          edit={edit}
          readView={readView}
          mapMissing={mapMissing}
        />
      </section>

      <section ref={textRef} aria-labelledby={`${titleId}-text`} className="space-y-3">
        <h3 id={`${titleId}-text`} className="text-sm font-semibold">
          {t('editor.chapter.text')}
        </h3>
        {blocks.map((block, i) => (
          <div key={block.id} data-block-id={block.id} className="space-y-1">
            {block.type === 'markdown' ? (
              <MarkdownField
                blockId={block.id}
                label={t('editor.chapter.textBlock', { index: kindNumbers[i] })}
                value={block.config.text}
                onChange={(text) => edit({ type: 'setBlockText', chapterId: chapter.id, blockId: block.id, text })}
              />
            ) : block.type === 'image' ? (
              <ImageBlockField
                storyId={storyId}
                uploads={uploads}
                chapterId={chapter.id}
                block={block}
                label={t('editor.chapter.imageBlock', { index: kindNumbers[i] })}
                edit={edit}
              />
            ) : block.type === 'button' ? (
              <ButtonBlockField
                chapterId={chapter.id}
                block={block}
                label={t('editor.chapter.buttonBlock', { index: kindNumbers[i] })}
                edit={edit}
              />
            ) : block.type === 'separator' ? (
              <SeparatorBlockField
                chapterId={chapter.id}
                block={block}
                label={t('editor.chapter.separatorBlock', { index: kindNumbers[i] })}
                edit={edit}
              />
            ) : (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                {t('editor.chapter.blockNotEditable')}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-1">
              {MOVES.map(({ by, Icon, label }) => (
                  <Button
                    key={by}
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    data-move={by}
                    disabled={by < 0 ? i === 0 : i === blocks.length - 1}
                    aria-label={t(label[block.type], { index: kindNumbers[i] })}
                    onClick={() => moveBlock(block.id, by)}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                ))}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => edit({ type: 'removeBlock', chapterId: chapter.id, blockId: block.id })}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                {t(REMOVE_LABELS[block.type], { index: kindNumbers[i] })}
              </Button>
            </div>
          </div>
        ))}
        <div className="flex flex-wrap items-start gap-2">
          {ADD_BLOCKS.map(addButton)}
          <StoryImagePicker
            label={t('editor.chapter.addImage')}
            disabled={blocksFull}
            upload={uploads.get(`add:${chapter.id}`)}
            onPick={(file) =>
              uploads.start(`add:${chapter.id}`, file, (asset) =>
                edit({ type: 'addImageBlock', chapterId: chapter.id, blockId: randomId(), assetId: asset.id }),
              )
            }
          />
        </div>
        {blocksFull && (
          <p id={`${titleId}-blocks-full`} className="text-xs text-muted-foreground">
            {t('editor.limits.blocks', { count: MAX_BLOCKS_PER_CHAPTER })}
          </p>
        )}
      </section>
    </div>
  );
}
