import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { BUTTON_LABEL_MAX_LENGTH, BUTTON_URL_MAX_LENGTH } from '@/components/widgets/button/definition';
import { isSafeHttpUrl } from '@/lib/safe-http-url';
import type { StoryChapter } from '@/types/api';
import type { DraftEdit } from './story-draft';

type ButtonBlock = Extract<NonNullable<StoryChapter['blocks']>[number], { type: 'button' }>;

interface ButtonBlockFieldProps {
  chapterId: string;
  block: ButtonBlock;
  label: string;
  edit: (change: DraftEdit) => void;
}

/** A button block: its label, an http or https address, and whether the link opens a new tab. */
export function ButtonBlockField({ chapterId, block, label, edit }: ButtonBlockFieldProps) {
  const { t } = useTranslation('stories');
  const id = useId();
  const labelId = `${id}-label`;
  const urlId = `${id}-url`;
  const newTabId = `${id}-new-tab`;
  const { label: text, url, new_tab: newTab } = block.config;
  const missingLabel = text.trim() === '';
  const badUrl = !isSafeHttpUrl(url);
  const setButton = (change: { label?: string; url?: string; newTab?: boolean }) =>
    edit({ type: 'setButton', chapterId, blockId: block.id, ...change });

  return (
    <fieldset className="space-y-3 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <div className="space-y-1">
        <Label htmlFor={labelId}>{t('editor.button.label')}</Label>
        <Input
          id={labelId}
          value={text}
          required
          aria-invalid={missingLabel}
          aria-describedby={missingLabel ? `${labelId}-error` : undefined}
          maxLength={BUTTON_LABEL_MAX_LENGTH}
          onChange={(event) => setButton({ label: event.target.value })}
        />
        {missingLabel && (
          <p id={`${labelId}-error`} className="text-xs text-destructive">
            {t('editor.button.labelRequired')}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Label htmlFor={urlId}>{t('editor.button.url')}</Label>
        <Input
          id={urlId}
          type="url"
          inputMode="url"
          autoComplete="off"
          value={url}
          required
          aria-invalid={badUrl}
          aria-describedby={`${urlId}-hint${badUrl ? ` ${urlId}-error` : ''}`}
          maxLength={BUTTON_URL_MAX_LENGTH}
          onChange={(event) => setButton({ url: event.target.value })}
        />
        <p id={`${urlId}-hint`} className="text-xs text-muted-foreground">
          {t('editor.button.urlHint')}
        </p>
        {badUrl && (
          <p id={`${urlId}-error`} className="text-xs text-destructive">
            {t('editor.button.urlInvalid')}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Checkbox
          id={newTabId}
          checked={newTab === true}
          onCheckedChange={(checked) => setButton({ newTab: checked === true })}
        />
        <Label htmlFor={newTabId}>{t('editor.button.newTab')}</Label>
      </div>
    </fieldset>
  );
}
