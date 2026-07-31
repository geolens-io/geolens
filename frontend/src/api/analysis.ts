import { apiFetch } from './client';
import type {
  AnalysisMaterializeRequest,
  AnalysisMaterializeResponse,
  AnalysisPreviewRequest,
  AnalysisPreviewResponse,
} from '@/types/api';

export async function previewAnalysis(
  datasetId: string,
  body: AnalysisPreviewRequest,
  // fix(#787 item 3): callers cancel a preview they no longer want. apiFetch
  // composes this with its own request timeout, so whichever fires first wins.
  signal?: AbortSignal,
): Promise<AnalysisPreviewResponse> {
  return apiFetch<AnalysisPreviewResponse>(`/datasets/${datasetId}/analysis/preview/`, {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
}

export async function materializeAnalysis(
  datasetId: string,
  body: AnalysisMaterializeRequest,
): Promise<AnalysisMaterializeResponse> {
  return apiFetch<AnalysisMaterializeResponse>(
    `/datasets/${datasetId}/analysis/materialize/`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  );
}
