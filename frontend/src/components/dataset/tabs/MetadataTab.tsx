import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ChevronDown, ChevronUp, History } from 'lucide-react';
import type { DatasetResponse } from '@/types/api';
import { ApiError } from '@/api/client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ContactsEditor } from '@/components/dataset/ContactsEditor';
import { KeywordsEditor } from '@/components/dataset/KeywordsEditor';
import { AiAssistButton, AiKeywordSuggestions } from '@/components/dataset/AiAssistButton';
import { ValidationStatus } from '@/components/dataset/ValidationStatus';
import { VersionHistory } from '@/components/dataset/VersionHistory';
import { ChangeHistory } from '@/components/dataset/ChangeHistory';
import { SourceQualityTab, type SourceQualityDraftField, type SourceQualityDraftValues } from '@/components/dataset/tabs/SourceQualityTab';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useKeywordSuggestions } from '@/hooks/use-ai-metadata';
import { useCreateKeyword, useKeywords } from '@/hooks/use-records';
import type { DatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';

interface MetadataTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  draftValues: SourceQualityDraftValues;
  onDraftSave: (field: SourceQualityDraftField, value: string) => void;
  onDraftDirtyChange: (field: SourceQualityDraftField, isDirty: boolean) => void;
  onNavigateToValidationField?: (field: string) => void;
}

export function MetadataTab({
  dataset,
  canEdit,
  capabilities,
  draftValues,
  onDraftSave,
  onDraftDirtyChange,
  onNavigateToValidationField,
}: MetadataTabProps) {
  const { t } = useTranslation('dataset');
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const { isAIAvailable } = useAIAvailability();
  const keywordSuggestions = useKeywordSuggestions();
  const createKeyword = useCreateKeyword(dataset.record_id);
  const existingKeywords = useKeywords(dataset.record_id);
  const [suggestedKeywords, setSuggestedKeywords] = useState<string[] | null>(null);

  return (
    <>
      <Card data-field-anchor="contacts">
        <CardHeader>
          <CardTitle className="text-base">{t('contacts.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ContactsEditor recordId={dataset.record_id} canEdit={canEdit} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">{t('keywords.title')}</CardTitle>
            {canEdit && isAIAvailable && (
              <AiAssistButton
                onClick={() =>
                  keywordSuggestions
                    .mutateAsync(dataset.id)
                    .then((response) => {
                      const existing = new Set(
                        (existingKeywords.data?.keywords ?? []).map((keyword) =>
                          keyword.keyword.toLowerCase(),
                        ),
                      );
                      const novel = response.keywords
                        .map((kw) => kw.keyword)
                        .filter(
                          (keyword) => !existing.has(keyword.toLowerCase()),
                        );
                      if (novel.length === 0) {
                        toast.info(t('ai.keywordsNoneSuggested'));
                      } else {
                        setSuggestedKeywords(novel);
                      }
                    })
                    .catch(() => toast.error(t('ai.keywordsGenerateFailed')))
                }
                isPending={keywordSuggestions.isPending}
              />
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <KeywordsEditor recordId={dataset.record_id} canEdit={canEdit} />
          {suggestedKeywords !== null && (
            <AiKeywordSuggestions
              keywords={suggestedKeywords}
              onAccept={async (selectedKeywords) => {
                try {
                  let added = 0;
                  for (const keyword of selectedKeywords) {
                    try {
                      await createKeyword.mutateAsync({ keyword });
                      added++;
                    } catch (error) {
                      if (error instanceof ApiError && error.status === 409) continue;
                      throw error;
                    }
                  }
                  setSuggestedKeywords(null);
                  if (added > 0) {
                    toast.success(t('ai.keywordsAdded', { count: added }));
                  } else {
                    toast.info(t('ai.keywordsAlreadyExist'));
                  }
                } catch {
                  toast.error(t('ai.keywordsAddFailed'));
                }
              }}
              onDiscard={() => setSuggestedKeywords(null)}
            />
          )}
        </CardContent>
      </Card>

      <SourceQualityTab
        dataset={dataset}
        canEdit={canEdit}
        datasetId={dataset.id}
        capabilities={capabilities}
        draftValues={draftValues}
        onDraftSave={onDraftSave}
        onDraftDirtyChange={onDraftDirtyChange}
      />

      <Card data-field-anchor="validation">
        <CardHeader>
          <CardTitle className="text-base">{t('validation.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ValidationStatus
            datasetId={dataset.id}
            onNavigateToField={onNavigateToValidationField}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <button
            type="button"
            onClick={() => setHistoryExpanded(!historyExpanded)}
            className="flex items-center gap-2 w-full text-start"
          >
            <History className="h-5 w-5" />
            <CardTitle className="text-base flex-1">{t('tabs.history')}</CardTitle>
            {historyExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
        </CardHeader>
        {historyExpanded && (
          <CardContent className="space-y-6">
            <VersionHistory datasetId={dataset.id} dataset={dataset} />
            {canEdit && <ChangeHistory datasetId={dataset.id} />}
          </CardContent>
        )}
      </Card>
    </>
  );
}
