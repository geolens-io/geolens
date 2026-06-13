import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { X, Loader2, AlertCircle } from 'lucide-react';
import { useKeywords, useCreateKeyword, useDeleteKeyword } from '@/components/dataset/hooks/use-records';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface KeywordsEditorProps {
  recordId: string;
  canEdit: boolean;
}

export function KeywordsEditor({ recordId, canEdit }: KeywordsEditorProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading, isError, refetch } = useKeywords(recordId);
  const createKeyword = useCreateKeyword(recordId);
  const deleteKeyword = useDeleteKeyword(recordId);

  const [input, setInput] = useState('');

  const handleAdd = async () => {
    const keyword = input.trim();
    if (!keyword) return;
    try {
      await createKeyword.mutateAsync({ keyword });
      toast.success(t('keywords.added'));
      setInput('');
    } catch {
      toast.error(t('keywords.addFailed'));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAdd();
    }
  };

  const handleDelete = async (keywordId: string) => {
    try {
      await deleteKeyword.mutateAsync(keywordId);
      toast.success(t('keywords.removed'));
    } catch {
      toast.error(t('keywords.removeFailed'));
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // GAP-034: surface fetch failures instead of collapsing into the empty
  // 'noKeywords' state (which would mislead the editor into re-adding dupes).
  if (isError) {
    return (
      <div
        role="alert"
        className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
      >
        <AlertCircle className="h-4 w-4 shrink-0" />
        <span>{t('keywords.loadError')}</span>
        <Button
          variant="ghost"
          size="sm"
          className="ms-auto h-7"
          onClick={() => refetch()}
        >
          {t('keywords.retry')}
        </Button>
      </div>
    );
  }

  const keywords = data?.keywords ?? [];

  return (
    <div className="space-y-2">
      {keywords.length === 0 && !canEdit && (
        <p className="text-sm text-muted-foreground">{t('keywords.noKeywords')}</p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {keywords.map((kw) => (
          <Badge key={kw.id} variant="secondary" className="gap-1">
            {kw.keyword}
            {canEdit && (
              <button
                type="button"
                onClick={() => handleDelete(kw.id)}
                className="ms-0.5 hover:text-destructive transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </Badge>
        ))}

        {canEdit && (
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('keywords.addPlaceholder')}
            className="h-7 w-40 text-sm"
            disabled={createKeyword.isPending}
          />
        )}
      </div>

      {canEdit && (
        <p className="text-xs text-muted-foreground">{t('keywords.normalizeHelp')}</p>
      )}
    </div>
  );
}
