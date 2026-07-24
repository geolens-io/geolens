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
): Promise<AnalysisPreviewResponse> {
  return apiFetch<AnalysisPreviewResponse>(`/datasets/${datasetId}/analysis/preview/`, {
    method: 'POST',
    body: JSON.stringify(body),
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
