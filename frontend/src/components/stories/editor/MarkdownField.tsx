import { useId, useLayoutEffect, useRef, useState } from 'react';
import { Bold, Heading2, Italic, Link2, List, ListOrdered, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { MARKDOWN_TEXT_MAX_LENGTH } from '@/components/widgets/markdown/definition';
import { parseStoredWidget } from '@/components/widgets/registry';
import { WidgetView } from '@/components/widgets/WidgetView';
import { applyMarkdownFormat, type MarkdownFormat } from './markdown-format';

const FORMATS: { format: MarkdownFormat; icon: LucideIcon }[] = [
  { format: 'bold', icon: Bold },
  { format: 'italic', icon: Italic },
  { format: 'heading', icon: Heading2 },
  { format: 'link', icon: Link2 },
  { format: 'bulletList', icon: List },
  { format: 'numberedList', icon: ListOrdered },
];

interface MarkdownFieldProps {
  blockId: string;
  label: string;
  value: string;
  onChange: (text: string) => void;
}

/** A Markdown text block: a textarea with a formatting toolbar, and a preview through the block's own renderer. */
export function MarkdownField({ blockId, label, value, onChange }: MarkdownFieldProps) {
  const { t } = useTranslation('stories');
  const textareaId = useId();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingSelection = useRef<[number, number] | null>(null);
  const [mode, setMode] = useState('write');

  useLayoutEffect(() => {
    const selection = pendingSelection.current;
    const textarea = textareaRef.current;
    if (!selection || !textarea) return;
    pendingSelection.current = null;
    textarea.focus();
    textarea.setSelectionRange(selection[0], selection[1]);
  }, [value]);

  function format(kind: MarkdownFormat) {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? value.length;
    const end = textarea?.selectionEnd ?? value.length;
    const edit = applyMarkdownFormat(value, start, end, kind);
    if (edit.text.length > MARKDOWN_TEXT_MAX_LENGTH) return;
    pendingSelection.current = [edit.start, edit.end];
    onChange(edit.text);
  }

  return (
    <Tabs value={mode} onValueChange={setMode} className="gap-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label htmlFor={textareaId}>{label}</Label>
        <TabsList className="h-8" wrapperClassName="self-start max-w-full">
          <TabsTrigger value="write">{t('editor.markdown.write')}</TabsTrigger>
          <TabsTrigger value="preview">{t('editor.markdown.preview')}</TabsTrigger>
        </TabsList>
      </div>
      {/* forceMount keeps the textarea, and its undo history, while previewing. */}
      <TabsContent value="write" forceMount className="space-y-1 data-[state=inactive]:hidden">
        <div role="toolbar" aria-label={t('editor.markdown.toolbar')} aria-controls={textareaId} className="flex flex-wrap gap-0.5">
          {FORMATS.map(({ format: kind, icon: Icon }) => (
            <Button
              key={kind}
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              aria-label={t(`editor.markdown.${kind}`)}
              title={t(`editor.markdown.${kind}`)}
              onClick={() => format(kind)}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
            </Button>
          ))}
        </div>
        <Textarea
          ref={textareaRef}
          id={textareaId}
          value={value}
          maxLength={MARKDOWN_TEXT_MAX_LENGTH}
          onChange={(event) => onChange(event.target.value)}
          rows={8}
          className="font-mono text-sm"
        />
      </TabsContent>
      <TabsContent value="preview" className="min-h-24 rounded-md border p-3">
        {value.trim() ? (
          <WidgetView
            parsed={parseStoredWidget({ id: blockId, type: 'markdown', v: 1, config: { text: value } }, 'story')}
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t('editor.markdown.empty')}</p>
        )}
      </TabsContent>
    </Tabs>
  );
}
