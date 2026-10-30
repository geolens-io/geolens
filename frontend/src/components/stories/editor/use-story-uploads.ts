import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { uploadStoryImage } from '@/api/stories';
import type { StoryAssetResponse } from '@/types/api';
import { captureAccount } from './same-account';
import { precheckStoryImage } from './story-image-limits';

/** One upload's progress (0 to 1) while it runs, and the refusal from the last attempt. */
export interface ImageUpload {
  progress: number | null;
  error: string | null;
}

const IDLE: ImageUpload = { progress: null, error: null };

export interface StoryUploads {
  get: (key: string) => ImageUpload;
  start: (key: string, file: File, onUploaded: (asset: StoryAssetResponse) => void) => void;
  /** Aborts every upload and forgets its progress and errors; none of them lands. */
  cancelAll: () => void;
  uploading: boolean;
}

/**
 * Image uploads for one story, keyed by where the image will land. They live
 * above the chapter editor, so an upload keeps going when another chapter is
 * shown; they're cancelled by `cancelAll` or when their owner unmounts.
 */
export function useStoryUploads(storyId: string): StoryUploads {
  const { t } = useTranslation('stories');
  const [state, setState] = useState<Record<string, ImageUpload>>({});
  const aborts = useRef(new Map<string, AbortController>());
  useEffect(() => {
    const running = aborts.current;
    return () => running.forEach((controller) => controller.abort());
  }, []);

  const patch = useCallback(
    (key: string, next: ImageUpload) =>
      setState((current) => {
        const was = current[key];
        return was?.progress === next.progress && was?.error === next.error ? current : { ...current, [key]: next };
      }),
    [],
  );

  const start = useCallback<StoryUploads['start']>(
    async (key, file, onUploaded) => {
      const refused = precheckStoryImage(file);
      if (refused) {
        patch(key, { progress: null, error: t(`common:${refused}`) });
        return;
      }
      const controller = new AbortController();
      aborts.current.set(key, controller);
      const same = captureAccount();
      patch(key, { progress: 0, error: null });
      try {
        const asset = await uploadStoryImage(
          storyId,
          file,
          // Whole percents only: every progress event would re-render the editor.
          (progress) => patch(key, { progress: Math.round(progress * 100) / 100, error: null }),
          controller.signal,
        );
        if (controller.signal.aborted) return;
        if (same()) onUploaded(asset);
        patch(key, IDLE);
      } catch (err) {
        if (controller.signal.aborted || !same()) return;
        patch(key, {
          progress: null,
          error: err instanceof Error && err.message ? err.message : t('common:errors.storyImageUnreadable'),
        });
      } finally {
        if (aborts.current.get(key) === controller) aborts.current.delete(key);
      }
    },
    [patch, storyId, t],
  );

  const cancelAll = useCallback(() => {
    aborts.current.forEach((controller) => controller.abort());
    aborts.current.clear();
    setState({});
  }, []);

  const get = useCallback((key: string) => state[key] ?? IDLE, [state]);
  const uploading = Object.values(state).some((upload) => upload.progress !== null);
  return { get, start, cancelAll, uploading };
}
