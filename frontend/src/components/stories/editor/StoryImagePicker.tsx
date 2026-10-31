import { useId, useRef } from 'react';
import { ImagePlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { STORY_IMAGE_TYPES } from './story-image-limits';
import type { ImageUpload } from './use-story-uploads';

interface StoryImagePickerProps {
  label: string;
  disabled?: boolean;
  upload: ImageUpload;
  onPick: (file: File) => void;
}

/** A button that picks an image to upload, with the upload's progress and any refusal shown beside it. */
export function StoryImagePicker({ label, disabled = false, upload, onPick }: StoryImagePickerProps) {
  const { t } = useTranslation('stories');
  const inputRef = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const { progress, error } = upload;

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
          if (file) onPick(file);
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
