import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { X, Loader2 } from 'lucide-react';
import { useKeywords, useCreateKeyword, useDeleteKeyword } from '@/hooks/use-records';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';

interface KeywordsEditorProps {
  recordId: string;
  canEdit: boolean;
}

export function KeywordsEditor({ recordId, canEdit }: KeywordsEditorProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useKeywords(recordId);
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
