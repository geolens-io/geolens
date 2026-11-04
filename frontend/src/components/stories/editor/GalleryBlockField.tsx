import { useId, useRef } from 'react';
import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { storyAssetPath } from '@/api/stories';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MAX_GALLERY_IMAGES } from '@/components/widgets/gallery/definition';
import { AssetImage } from '@/components/widgets/image/AssetImage';
import {
  IMAGE_ALT_MAX_LENGTH,
  IMAGE_CAPTION_MAX_LENGTH,
  imageNeedsAlt,
  readerAlt,
} from '@/components/widgets/image/definition';
import type { StoryChapter } from '@/types/api';
import type { DraftEdit, GalleryKind } from './story-draft';
import { StoryImagePicker } from './StoryImagePicker';
import { useMoveFocus } from './use-move-focus';
import type { StoryUploads } from './use-story-uploads';

type GalleryBlock = Extract<NonNullable<StoryChapter['blocks']>[number], { type: GalleryKind }>;
type GalleryImage = GalleryBlock['config']['images'][number];

interface GalleryBlockFieldProps {
  storyId: string;
  uploads: StoryUploads;
  chapterId: string;
  block: GalleryBlock;
  label: string;
  edit: (change: DraftEdit) => void;
}

interface GalleryImageRowProps {
  storyId: string;
  chapterId: string;
  blockId: string;
  image: GalleryImage;
  index: number;
  count: number;
  edit: (change: DraftEdit) => void;
  onMove: (assetId: string, by: -1 | 1) => void;
}

function GalleryImageRow({ storyId, chapterId, blockId, image, index, count, edit, onMove }: GalleryImageRowProps) {
  const { t } = useTranslation('stories');
  const altId = useId();
  const decorativeId = useId();
  const captionId = useId();
  const decorative = image.decorative === true;
  const missingAlt = imageNeedsAlt(image);
  const number = index + 1;
  const setImage = (change: { alt?: string; decorative?: boolean; caption?: string }) =>
    edit({ type: 'setGalleryImage', chapterId, blockId, assetId: image.asset_id, ...change });

  return (
    <li data-image-id={image.asset_id} data-move-scope className="space-y-3 rounded-md border p-3">
      <p className="text-sm font-medium">{t('editor.gallery.imageNumber', { index: number })}</p>
      <AssetImage
        path={storyAssetPath(storyId, image.asset_id)}
        alt={readerAlt(image)}
        className="max-h-32 rounded-md object-contain"
        placeholderClassName="h-24 w-full"
        fallback={
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            {t('editor.image.notShown')}
          </p>
        }
      />
      <div className="flex items-center gap-2">
        <Checkbox
          id={decorativeId}
          checked={decorative}
          onCheckedChange={(checked) => setImage({ decorative: checked === true })}
        />
        <Label htmlFor={decorativeId}>{t('editor.gallery.decorative', { index: number })}</Label>
      </div>
      {!decorative && (
        <div className="space-y-1">
          <Label htmlFor={altId}>{t('editor.gallery.alt', { index: number })}</Label>
          <Input
            id={altId}
            value={image.alt ?? ''}
            required
            aria-invalid={missingAlt}
            aria-describedby={missingAlt ? `${altId}-error` : undefined}
            maxLength={IMAGE_ALT_MAX_LENGTH}
            onChange={(event) => setImage({ alt: event.target.value })}
          />
          {missingAlt && (
            <p id={`${altId}-error`} className="text-xs text-destructive">
              {t('editor.image.altRequired')}
            </p>
          )}
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor={captionId}>{t('editor.gallery.caption', { index: number })}</Label>
        <Input
          id={captionId}
          value={image.caption ?? ''}
          maxLength={IMAGE_CAPTION_MAX_LENGTH}
          onChange={(event) => setImage({ caption: event.target.value })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {([-1, 1] as const).map((by) => (
          <Button
            key={by}
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            data-move={by}
            disabled={by < 0 ? index === 0 : index === count - 1}
            aria-label={t(by < 0 ? 'editor.gallery.moveUp' : 'editor.gallery.moveDown', { index: number })}
            onClick={() => onMove(image.asset_id, by)}
          >
            {by < 0 ? (
              <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
            )}
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-destructive"
          disabled={count === 1}
          onClick={() => edit({ type: 'removeGalleryImage', chapterId, blockId, assetId: image.asset_id })}
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
          {t('editor.gallery.remove', { index: number })}
        </Button>
      </div>
    </li>
  );
}

/**
 * A gallery or carousel block: its images in reading order, each with alt text
 * (required unless decorative) and an optional caption, and an upload for more.
 */
export function GalleryBlockField({ storyId, uploads, chapterId, block, label, edit }: GalleryBlockFieldProps) {
  const { t } = useTranslation('stories');
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const images = block.config.images;
  const full = images.length >= MAX_GALLERY_IMAGES;
  const markMoved = useMoveFocus(listRef, 'data-image-id', images);
  const key = `gallery:${block.id}`;

  return (
    <fieldset className="space-y-3 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <p id={`${listId}-limit`} className="text-xs text-muted-foreground">
        {t('editor.gallery.limit', { count: MAX_GALLERY_IMAGES })}
      </p>
      <ul ref={listRef} className="space-y-3">
        {images.map((image, i) => (
          <GalleryImageRow
            key={image.asset_id}
            storyId={storyId}
            chapterId={chapterId}
            blockId={block.id}
            image={image}
            index={i}
            count={images.length}
            edit={edit}
            onMove={(assetId, by) => {
              markMoved(assetId, by);
              edit({ type: 'moveGalleryImage', chapterId, blockId: block.id, assetId, by });
            }}
          />
        ))}
      </ul>
      <StoryImagePicker
        label={t('editor.gallery.addImage')}
        disabled={full}
        testId="story-gallery-image-input"
        upload={uploads.get(key)}
        onPick={(file) =>
          uploads.start(key, file, (asset) =>
            edit({ type: 'addGalleryImage', chapterId, blockId: block.id, assetId: asset.id }),
          )
        }
      />
    </fieldset>
  );
}
