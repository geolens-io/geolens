import { apiFetch } from './client';
import type { AnalysisPreviewRequest, AnalysisPreviewResponse } from '@/types/api';

export async function previewAnalysis(
  datasetId: string,
  body: AnalysisPreviewRequest,
): Promise<AnalysisPreviewResponse> {
  return apiFetch<AnalysisPreviewResponse>(`/datasets/${datasetId}/analysis/preview/`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
