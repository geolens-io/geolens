import { useMutation } from '@tanstack/react-query';
import { generateSummaryDraft, generateKeywordSuggestions, generateLineageDraft, generateQualityStatementDraft } from '@/api/ai-metadata';

export function useSummaryDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateSummaryDraft(datasetId),
  });
}

export function useKeywordSuggestions() {
  return useMutation({
    mutationFn: (datasetId: string) => generateKeywordSuggestions(datasetId),
  });
}

export function useLineageDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateLineageDraft(datasetId),
  });
}

export function useQualityStatementDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateQualityStatementDraft(datasetId),
  });
}
