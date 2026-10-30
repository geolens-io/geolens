import { useEffect, useId, useRef } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { randomId } from '@/lib/random-id';
import type { StoryCamera, StoryChapter } from '@/types/api';
import { ImageBlockField } from './ImageBlockField';
import { MarkdownField } from './MarkdownField';
import { SceneEditor } from './SceneEditor';
import { CHAPTER_TITLE_MAX_LENGTH, MAX_BLOCKS_PER_CHAPTER, type DraftEdit } from './story-draft';
import { StoryImagePicker } from './StoryImagePicker';

interface ChapterEditorProps {
  storyId: string;
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

      <section aria-labelledby={`${titleId}-text`} className="space-y-3">
        <h3 id={`${titleId}-text`} className="text-sm font-semibold">
          {t('editor.chapter.text')}
        </h3>
        {blocks.map((block, i) => (
          <div key={block.id} className="space-y-1">
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
                chapterId={chapter.id}
                block={block}
                label={t('editor.chapter.imageBlock', { index: kindNumbers[i] })}
                edit={edit}
              />
            ) : (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                {t('editor.chapter.blockNotEditable')}
              </p>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => edit({ type: 'removeBlock', chapterId: chapter.id, blockId: block.id })}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              {block.type === 'image'
                ? t('editor.chapter.removeImage', { index: kindNumbers[i] })
                : t('editor.chapter.removeBlock', { index: kindNumbers[i] })}
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-start gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={blocksFull}
            aria-describedby={blocksFull ? `${titleId}-blocks-full` : undefined}
            onClick={() => edit({ type: 'addTextBlock', chapterId: chapter.id, blockId: randomId() })}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('editor.chapter.addTextBlock')}
          </Button>
          <StoryImagePicker
            storyId={storyId}
            label={t('editor.chapter.addImage')}
            disabled={blocksFull}
            onUploaded={(asset) =>
              edit({ type: 'addImageBlock', chapterId: chapter.id, blockId: randomId(), assetId: asset.id })
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
