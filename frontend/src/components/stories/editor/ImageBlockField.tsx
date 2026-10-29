import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { storyAssetPath } from '@/api/stories';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { AssetImage } from '@/components/widgets/image/AssetImage';
import {
  IMAGE_ALT_MAX_LENGTH,
  IMAGE_CAPTION_MAX_LENGTH,
  validImageAlt,
} from '@/components/widgets/image/definition';
import type { StoryChapter } from '@/types/api';
import type { DraftEdit } from './story-draft';
import { StoryImagePicker } from './StoryImagePicker';

type ImageBlock = Extract<NonNullable<StoryChapter['blocks']>[number], { type: 'image' }>;

interface ImageBlockFieldProps {
  storyId: string;
  chapterId: string;
  block: ImageBlock;
  label: string;
  edit: (change: DraftEdit) => void;
}

/** An image block: a preview, its required alt text and optional caption, and a replacement upload. */
export function ImageBlockField({ storyId, chapterId, block, label, edit }: ImageBlockFieldProps) {
  const { t } = useTranslation('stories');
  const altId = useId();
  const captionId = useId();
  const missingAlt = !validImageAlt(block.config.alt);
  const setImage = (change: { assetId?: string; alt?: string; caption?: string }) =>
    edit({ type: 'setImage', chapterId, blockId: block.id, ...change });

  return (
    <fieldset className="space-y-3 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <AssetImage
        path={storyAssetPath(storyId, block.asset_id)}
        alt={block.config.alt}
        className="max-h-48 rounded-md object-contain"
        placeholderClassName="h-32 w-full"
        fallback={
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            {t('editor.image.notShown')}
          </p>
        }
      />
      <div className="space-y-1">
        <Label htmlFor={altId}>{t('editor.image.alt')}</Label>
        <Input
          id={altId}
          value={block.config.alt}
          required
          aria-invalid={missingAlt}
          aria-describedby={`${altId}-hint${missingAlt ? ` ${altId}-error` : ''}`}
          maxLength={IMAGE_ALT_MAX_LENGTH}
          onChange={(event) => setImage({ alt: event.target.value })}
        />
        <p id={`${altId}-hint`} className="text-xs text-muted-foreground">
          {t('editor.image.altHint')}
        </p>
        {missingAlt && (
          <p id={`${altId}-error`} className="text-xs text-destructive">
            {t('editor.image.altRequired')}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Label htmlFor={captionId}>{t('editor.image.caption')}</Label>
        <Input
          id={captionId}
          value={block.config.caption ?? ''}
          maxLength={IMAGE_CAPTION_MAX_LENGTH}
          onChange={(event) => setImage({ caption: event.target.value })}
        />
      </div>
      <StoryImagePicker
        storyId={storyId}
        label={t('editor.image.replace')}
        onUploaded={(asset) => setImage({ assetId: asset.id })}
      />
    </fieldset>
  );
}
