import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { STORY_SUMMARY_MAX_LENGTH, STORY_TITLE_MAX_LENGTH } from './editor/story-draft';

interface StoryTextFieldsProps {
  title: string;
  summary: string;
  onTitleChange: (title: string) => void;
  onSummaryChange: (summary: string) => void;
}

/** A story's title and summary inputs, with the server's length limits. */
export function StoryTextFields({ title, summary, onTitleChange, onSummaryChange }: StoryTextFieldsProps) {
  const { t } = useTranslation('stories');
  const titleId = useId();
  const summaryId = useId();
  return (
    <>
      <div className="space-y-1">
        <Label htmlFor={titleId}>{t('details.titleLabel')}</Label>
        <Input
          id={titleId}
          value={title}
          required
          maxLength={STORY_TITLE_MAX_LENGTH}
          onChange={(event) => onTitleChange(event.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={summaryId}>{t('details.summaryLabel')}</Label>
        <Textarea
          id={summaryId}
          value={summary}
          maxLength={STORY_SUMMARY_MAX_LENGTH}
          rows={3}
          onChange={(event) => onSummaryChange(event.target.value)}
        />
      </div>
    </>
  );
}
