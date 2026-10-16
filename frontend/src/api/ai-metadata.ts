import { apiFetch } from './client';

interface SummaryDraftResponse {
  draft: string;
}

interface KeywordSuggestion {
  keyword: string;
  keyword_type: string; // 'theme' | 'place' | 'temporal'
}

interface KeywordSuggestionsResponse {
  keywords: KeywordSuggestion[];
}

interface LineageDraftResponse {
  draft: string;
}

interface QualityStatementDraftResponse {
  draft: string;
}

export async function generateSummaryDraft(datasetId: string): Promise<SummaryDraftResponse> {
  return apiFetch<SummaryDraftResponse>('/ai/metadata/summary/', {
    method: 'POST',
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}

export async function generateKeywordSuggestions(datasetId: string): Promise<KeywordSuggestionsResponse> {
  return apiFetch<KeywordSuggestionsResponse>('/ai/metadata/keywords/', {
    method: 'POST',
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}

export async function generateLineageDraft(datasetId: string): Promise<LineageDraftResponse> {
  return apiFetch<LineageDraftResponse>('/ai/metadata/lineage/', {
    method: 'POST',
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}

export async function generateQualityStatementDraft(datasetId: string): Promise<QualityStatementDraftResponse> {
  return apiFetch<QualityStatementDraftResponse>('/ai/metadata/quality-statement/', {
    method: 'POST',
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}
