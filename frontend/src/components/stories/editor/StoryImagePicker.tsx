import { useEffect, useId, useRef, useState } from 'react';
import { ImagePlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { uploadStoryImage } from '@/api/stories';
import { Button } from '@/components/ui/button';
import type { StoryAssetResponse } from '@/types/api';
import { captureAccount } from './same-account';
import { precheckStoryImage, STORY_IMAGE_TYPES } from './story-image-limits';

interface StoryImagePickerProps {
  storyId: string;
  label: string;
  disabled?: boolean;
  onUploaded: (asset: StoryAssetResponse) => void;
}

/**
 * A button that uploads a chosen image to the story, with its progress and
 * any refusal shown beside it. The upload is cancelled if the picker unmounts.
 */
export function StoryImagePicker({ storyId, label, disabled = false, onUploaded }: StoryImagePickerProps) {
  const { t } = useTranslation('stories');
  const inputRef = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();
  useEffect(() => () => abort.current?.abort(), []);

  async function upload(file: File) {
    setError(null);
    const refused = precheckStoryImage(file);
    if (refused) {
      setError(t(`common:${refused}`));
      return;
    }
    const controller = new AbortController();
    abort.current = controller;
    const same = captureAccount();
    setProgress(0);
    try {
      const asset = await uploadStoryImage(storyId, file, setProgress, controller.signal);
      if (same()) onUploaded(asset);
    } catch (err) {
      if (controller.signal.aborted || !same()) return;
      setError(err instanceof Error && err.message ? err.message : t('common:errors.storyImageUnreadable'));
    } finally {
      abort.current = null;
      setProgress(null);
    }
  }

  const uploading = progress !== null;
  const percent = uploading ? Math.round(progress * 100) : 0;
  return (
    <div className="space-y-1">
      <input
        ref={inputRef}
        type="file"
        accept={STORY_IMAGE_TYPES.join(',')}
        hidden
        data-testid="story-image-input"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared so choosing the same file again uploads it again.
          event.target.value = '';
          if (file) void upload(file);
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || uploading}
        aria-describedby={error ? errorId : undefined}
        onClick={() => inputRef.current?.click()}
      >
        <ImagePlus className="h-4 w-4" aria-hidden="true" />
        {label}
      </Button>
      {uploading && (
        <div className="space-y-1">
          <div
            role="progressbar"
            aria-label={t('editor.image.progress')}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-1 w-full overflow-hidden rounded-full bg-surface-2"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-150 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {progress < 1 ? t('editor.image.uploading', { percent }) : t('editor.image.processing')}
          </p>
        </div>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
