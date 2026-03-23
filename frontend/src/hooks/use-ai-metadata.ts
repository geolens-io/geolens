import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { generateSummaryDraft, generateKeywordSuggestions, generateLineageDraft, generateQualityStatementDraft } from '@/api/ai-metadata';

export function useSummaryDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateSummaryDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to generate summary');
    },
  });
}

export function useKeywordSuggestions() {
  return useMutation({
    mutationFn: (datasetId: string) => generateKeywordSuggestions(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to generate keywords');
    },
  });
}

export function useLineageDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateLineageDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to generate lineage');
    },
  });
}

export function useQualityStatementDraft() {
  return useMutation({
    mutationFn: (datasetId: string) => generateQualityStatementDraft(datasetId),
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to generate quality statement');
    },
  });
}
