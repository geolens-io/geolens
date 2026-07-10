import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';

interface AiAssistButtonProps {
  onClick: () => void;
  isPending: boolean;
  label?: string;
}

export function AiAssistButton({ onClick, isPending, label }: AiAssistButtonProps) {
  const { t } = useTranslation('dataset');
  const resolvedLabel = label ?? t('ai.assist');

  return (
    <Button
      variant="outline"
      size="xs"
      onClick={onClick}
      disabled={isPending}
      // The assist buttons were muted ghost buttons users didn't notice; an
      // outline + primary tint makes them read as a discoverable AI action.
      className="border-primary/40 text-primary hover:bg-primary/10 hover:text-primary"
    >
      {isPending ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Sparkles className="h-3.5 w-3.5" />
      )}
      {resolvedLabel}
    </Button>
  );
}

interface AiDraftPreviewProps {
  draft: string;
  onAccept: (editedText: string) => void;
  onDiscard: () => void;
}

export function AiDraftPreview({ draft, onAccept, onDiscard }: AiDraftPreviewProps) {
  const { t } = useTranslation('dataset');
  const [editedText, setEditedText] = useState(draft);

  return (
    <div className="border-s-4 border-muted bg-muted/30 rounded-e-md p-3 space-y-2">
      <Badge variant="secondary" className="text-xs">
        {t('ai.draft')}
      </Badge>
      <Textarea
        value={editedText}
        onChange={(e) => setEditedText(e.target.value)}
        className="min-h-[4rem] resize-none"
        rows={4}
      />
      <div className="flex items-center gap-2">
        <Button size="xs" onClick={() => onAccept(editedText)}>
          {t('ai.accept')}
        </Button>
        <Button variant="ghost" size="xs" onClick={onDiscard}>
          {t('ai.discard')}
        </Button>
      </div>
    </div>
  );
}

interface AiKeywordSuggestionsProps {
  keywords: string[];
  onAccept: (selectedKeywords: string[]) => void;
  onDiscard: () => void;
}

export function AiKeywordSuggestions({ keywords, onAccept, onDiscard }: AiKeywordSuggestionsProps) {
  const { t } = useTranslation('dataset');
  const [selected, setSelected] = useState<Set<string>>(new Set(keywords));

  function toggleKeyword(keyword: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(keyword)) {
        next.delete(keyword);
      } else {
        next.add(keyword);
      }
      return next;
    });
  }

  return (
    <div className="border-s-4 border-muted bg-muted/30 rounded-e-md p-3 space-y-2">
      <Badge variant="secondary" className="text-xs">
        {t('ai.draft')}
      </Badge>
      <div className="flex flex-wrap gap-1.5">
        {keywords.map((kw) => (
          <Badge
            key={kw}
            variant={selected.has(kw) ? 'default' : 'outline'}
            className="cursor-pointer select-none"
            onClick={() => toggleKeyword(kw)}
          >
            {kw}
          </Badge>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button size="xs" onClick={() => onAccept([...selected])} disabled={selected.size === 0}>
          {t('ai.addSelected')}
        </Button>
        <Button variant="ghost" size="xs" onClick={onDiscard}>
          {t('ai.discard')}
        </Button>
      </div>
    </div>
  );
}
