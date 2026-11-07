import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  approvedFrameHost,
  FRAME_TITLE_MAX_LENGTH,
  FRAME_URL_MAX_LENGTH,
  frameUrlHost,
} from '@/components/widgets/embed/frame';
import type { StoryChapter, StoryFrameHost } from '@/types/api';
import type { DraftEdit } from './story-draft';

type FrameBlock = Extract<NonNullable<StoryChapter['blocks']>[number], { type: 'embed' | 'video' }>;

interface FrameBlockFieldProps {
  chapterId: string;
  block: FrameBlock;
  label: string;
  /** The approved hosts; undefined while they load. */
  hosts: readonly StoryFrameHost[] | undefined;
  edit: (change: DraftEdit) => void;
}

/** An embed or video block: an https address on an approved host, and the frame's required title. */
export function FrameBlockField({ chapterId, block, label, hosts, edit }: FrameBlockFieldProps) {
  const { t } = useTranslation('stories');
  const id = useId();
  const urlId = `${id}-url`;
  const titleId = `${id}-title`;
  const { url, title } = block.config;
  const host = frameUrlHost(url);
  const urlError =
    url === ''
      ? null
      : host === null
        ? t('editor.frame.urlInvalid')
        : hosts !== undefined && approvedFrameHost(hosts, url) === undefined
          ? t('editor.frame.hostNotApproved', { host })
          : null;
  const missingTitle = title.trim() === '';
  const setFrame = (change: { url?: string; title?: string }) =>
    edit({ type: 'setFrame', chapterId, blockId: block.id, ...change });

  return (
    <fieldset className="space-y-3 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <div className="space-y-1">
        <Label htmlFor={urlId}>{t(block.type === 'video' ? 'editor.frame.videoUrl' : 'editor.frame.embedUrl')}</Label>
        <Input
          id={urlId}
          type="url"
          inputMode="url"
          autoComplete="off"
          value={url}
          required
          aria-invalid={url === '' || urlError !== null}
          aria-describedby={`${urlId}-hint${urlError ? ` ${urlId}-error` : ''}`}
          maxLength={FRAME_URL_MAX_LENGTH}
          onChange={(event) => setFrame({ url: event.target.value })}
        />
        <p id={`${urlId}-hint`} className="text-xs text-muted-foreground">
          {hosts && hosts.length > 0
            ? t('editor.frame.urlHint', { hosts: hosts.map((entry) => entry.host).join(', ') })
            : t('editor.frame.noHosts')}
        </p>
        {urlError && (
          <p id={`${urlId}-error`} className="text-xs text-destructive">
            {urlError}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Label htmlFor={titleId}>{t('editor.frame.title')}</Label>
        <Input
          id={titleId}
          value={title}
          required
          aria-invalid={missingTitle}
          aria-describedby={`${titleId}-hint${missingTitle ? ` ${titleId}-error` : ''}`}
          maxLength={FRAME_TITLE_MAX_LENGTH}
          onChange={(event) => setFrame({ title: event.target.value })}
        />
        <p id={`${titleId}-hint`} className="text-xs text-muted-foreground">
          {t('editor.frame.titleHint')}
        </p>
        {missingTitle && (
          <p id={`${titleId}-error`} className="text-xs text-destructive">
            {t('editor.frame.titleRequired')}
          </p>
        )}
      </div>
    </fieldset>
  );
}
