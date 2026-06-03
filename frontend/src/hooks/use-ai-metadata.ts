import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { generateSummaryDraft, generateKeywordSuggestions, generateLineageDraft, generateQualityStatementDraft } from '@/api/ai-metadata';

export function useSummaryDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateSummaryDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || i18n.t('common:errors.aiSummaryFailed'));
    },
  });
}

export function useKeywordSuggestions() {
  return useMutation({
    mutationFn: (datasetId: string) => generateKeywordSuggestions(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || i18n.t('common:errors.aiKeywordsFailed'));
    },
  });
}

export function useLineageDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateLineageDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || i18n.t('common:errors.aiLineageFailed'));
    },
  });
}

export function useQualityStatementDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateQualityStatementDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || i18n.t('common:errors.aiQualityFailed'));
    },
  });
}
