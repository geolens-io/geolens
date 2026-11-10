import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { WidgetEditorProps } from '../contract';
import { MARKDOWN_TEXT_MAX_LENGTH, type MarkdownTextConfig } from './definition';

export default function MarkdownTextEditor({ config, onChange, idPrefix }: WidgetEditorProps<MarkdownTextConfig>) {
  const { t } = useTranslation('widgets');
  return (
    <div className="space-y-1.5">
      <Label className="text-xs" htmlFor={`${idPrefix}-text`}>
        {t('types.markdown.label')}
      </Label>
      <Textarea
        id={`${idPrefix}-text`}
        aria-describedby={`${idPrefix}-text-hint`}
        rows={6}
        maxLength={MARKDOWN_TEXT_MAX_LENGTH}
        className="font-mono text-sm"
        value={config.text}
        onChange={(event) => onChange({ text: event.target.value })}
      />
      <p id={`${idPrefix}-text-hint`} className="text-xs text-muted-foreground">
        {t('types.markdown.sourceHint')}
      </p>
    </div>
  );
}
