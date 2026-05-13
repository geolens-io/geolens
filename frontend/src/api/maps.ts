import { apiFetch, ApiError } from './client';
import type {
  MapResponse,
  DuplicateMapResponse,
  MapListResponse,
  MapCreateRequest,
  MapUpdateRequest,
  MapLayerDiffRequest,
  MapLayerResponse,
  MapLayerInput,
  MapHistoryListResponse,
  SharedMapResponse,
  ShareTokenResponse,
  MapGenerateRequest,
  MapGenerateResponse,
  ColumnValuesResponse,
  ColumnStatsResponse,
  ChatMapLayer,
  ChatHistoryMessage,
  ChatRequest,
  ChatResponse,
  VisibilityCheckResponse,
  MapStyleImportResponse,
  MapIconListResponse,
  MapIconResponse,
} from '@/types/api';
import { API_BASE } from '@/lib/constants';
import { useAuthStore } from '@/stores/auth-store';
import { normalizeLayerStyleState } from '@/lib/normalize-style-config';
import { normalizeSavedMap } from '@/lib/normalize-saved-map';

export async function listMaps(
  params: {
    skip?: number;
    limit?: number;
    search?: string;
    sort_by?: string;
    sort_dir?: string;
    visibility?: string;
  } = {},
): Promise<MapListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.search) query.set('search', params.search);
  if (params.sort_by) query.set('sort_by', params.sort_by);
  if (params.sort_dir) query.set('sort_dir', params.sort_dir);
  if (params.visibility) query.set('visibility', params.visibility);
  const qs = query.toString();
  return apiFetch<MapListResponse>(`/maps/${qs ? `?${qs}` : ''}`);
}

export async function getMap(id: string): Promise<MapResponse> {
  const resp = await apiFetch<MapResponse>(`/maps/${id}`);
  if (resp.layers) {
    for (const l of resp.layers) {
      const normalized = normalizeLayerStyleState(l.style_config, l.paint, l.dataset_geometry_type);
      l.style_config = normalized.style_config;
      l.paint = normalized.paint;
    }
  }
  // Apply map-level normalization: guarantees basemap_style is a non-empty string,
  // show_basemap_labels is a boolean, widgets is string[]|null. Composes with
  // the per-layer normalizeLayerStyleState loop above; does NOT reassign resp.layers
  // because the loop already mutated those elements in place.
  const mapNorm = normalizeSavedMap(resp);
  resp.basemap_style = mapNorm.basemap_style;
  resp.show_basemap_labels = mapNorm.show_basemap_labels;
  resp.basemap_config = mapNorm.basemap_config;
  resp.terrain_config = mapNorm.terrain_config;
  resp.widgets = mapNorm.widgets;
  return resp;
}

export async function getMapHistory(
  mapId: string,
  params: { skip?: number; limit?: number } = {},
): Promise<MapHistoryListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<MapHistoryListResponse>(`/maps/${mapId}/history${qs ? `?${qs}` : ''}`);
}

export async function createMap(data: MapCreateRequest): Promise<MapResponse> {
  return apiFetch<MapResponse>('/maps/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateMap(
  id: string,
  data: MapUpdateRequest,
): Promise<MapResponse> {
  return apiFetch<MapResponse>(`/maps/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function patchMapLayers(
  id: string,
  diff: MapLayerDiffRequest,
): Promise<MapResponse> {
  const resp = await apiFetch<MapResponse>(`/maps/${id}/layers`, {
    method: 'PATCH',
    body: JSON.stringify(diff),
  });
  if (resp.layers) {
    for (const l of resp.layers) {
      const normalized = normalizeLayerStyleState(l.style_config, l.paint, l.dataset_geometry_type);
      l.style_config = normalized.style_config;
      l.paint = normalized.paint;
    }
  }
  return resp;
}

export async function duplicateMap(mapId: string): Promise<DuplicateMapResponse> {
  return apiFetch<DuplicateMapResponse>(`/maps/${mapId}/duplicate/`, {
    method: 'POST',
  });
}

export async function deleteMap(id: string): Promise<void> {
  await apiFetch(`/maps/${id}`, {
    method: 'DELETE',
  });
}

export async function addLayerToMapApi(
  mapId: string,
  data: MapLayerInput,
): Promise<MapLayerResponse> {
  return apiFetch<MapLayerResponse>(`/maps/${mapId}/layers`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function removeLayerFromMapApi(
  mapId: string,
  layerId: string,
): Promise<void> {
  await apiFetch(`/maps/${mapId}/layers/${layerId}`, {
    method: 'DELETE',
  });
}

export async function getSharedMap(token: string, apiKey?: string): Promise<SharedMapResponse> {
  const extraHeaders: Record<string, string> = {};
  if (apiKey) {
    extraHeaders['X-Api-Key'] = apiKey;
  }
  const resp = await apiFetch<SharedMapResponse>(`/maps/shared/${token}`, { headers: extraHeaders });
  if (resp.layers) {
    for (const l of resp.layers) {
      const normalized = normalizeLayerStyleState(l.style_config, l.paint, l.geometry_type);
      l.style_config = normalized.style_config;
      l.paint = normalized.paint;
    }
  }
  // Apply map-level normalization: SharedMapResponse.show_basemap_labels is optional
  // (older shared payloads omit it); normalizeSavedMap defaults it to true (BSR-22).
  // Does NOT reassign resp.layers — per-layer mutations already applied above.
  const mapNorm = normalizeSavedMap(resp);
  resp.basemap_style = mapNorm.basemap_style;
  resp.show_basemap_labels = mapNorm.show_basemap_labels;
  resp.basemap_config = mapNorm.basemap_config;
  resp.terrain_config = mapNorm.terrain_config;
  // widgets: SharedMapResponse has no widgets field; normalization result is intentionally
  // discarded. When SharedMapResponse gains widgets, add: resp.widgets = mapNorm.widgets;
  return resp;
}

export async function checkMapVisibility(mapId: string): Promise<VisibilityCheckResponse> {
  return apiFetch<VisibilityCheckResponse>(`/maps/${mapId}/visibility-check/`);
}

export async function exportMapStyleJson(mapId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/maps/${mapId}/style.json`);
}

export async function importMapStyleJson(style: Record<string, unknown>): Promise<MapStyleImportResponse> {
  return apiFetch<MapStyleImportResponse>('/maps/import', {
    method: 'POST',
    body: JSON.stringify(style),
  });
}

export async function listMapIcons(): Promise<MapIconListResponse> {
  return apiFetch<MapIconListResponse>('/maps/icons');
}

export async function uploadMapIcon(file: File): Promise<MapIconResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return apiFetch<MapIconResponse>('/maps/icons', {
    method: 'POST',
    body: formData,
  });
}

export async function publishMap(id: string, visibility: 'public' | 'private' | 'internal'): Promise<MapResponse> {
  return apiFetch<MapResponse>(`/maps/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ visibility }),
  });
}

export async function createShareToken(
  mapId: string,
  expiresAt?: string,
): Promise<ShareTokenResponse> {
  const body = expiresAt ? JSON.stringify({ expires_at: expiresAt }) : undefined;
  return apiFetch<ShareTokenResponse>(`/maps/${mapId}/share/`, {
    method: 'POST',
    ...(body && { body }),
  });
}

export async function revokeShareToken(mapId: string): Promise<void> {
  await apiFetch(`/maps/${mapId}/share/`, { method: 'DELETE' });
}

export async function updateShareTokenExpiration(
  mapId: string,
  expiresAt: string | null,
): Promise<ShareTokenResponse> {
  return apiFetch<ShareTokenResponse>(`/maps/${mapId}/share/`, {
    method: 'PATCH',
    body: JSON.stringify({ expires_at: expiresAt }),
  });
}

export async function getMapShareToken(mapId: string): Promise<ShareTokenResponse | null> {
  return apiFetch<ShareTokenResponse | null>(`/maps/${mapId}/share/`);
}

export async function uploadThumbnail(mapId: string, dataUri: string): Promise<void> {
  await apiFetch(`/maps/${mapId}/thumbnail/`, {
    method: 'PUT',
    body: JSON.stringify({ data_uri: dataUri }),
  });
}

export async function fetchDatasetMaps(datasetId: string): Promise<MapListResponse> {
  return apiFetch<MapListResponse>(`/datasets/${datasetId}/maps/`);
}

export async function generateMap(data: MapGenerateRequest): Promise<MapGenerateResponse> {
  return apiFetch<MapGenerateResponse>('/ai/generate-map/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function* streamGenerateMap(
  data: MapGenerateRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/ai/generate-map/stream/`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
    signal,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch { /* not JSON */ }
    throw new Error(detail);
  }

  if (!response.body) throw new Error('No response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = 'message';
  let dataLines: string[] = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const rawLines = buffer.split('\n');
      buffer = rawLines.pop() ?? '';

      for (const rawLine of rawLines) {
        // SSE spec allows \r\n, \n, or \r as line terminators. sse-starlette
        // uses \r\n, so after splitting on \n every line carries a trailing
        // \r that must be stripped before the empty-line frame boundary check.
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (line.startsWith('event: ')) {
          eventType = line.slice(7);
        } else if (line.startsWith('data: ')) {
          dataLines.push(line.slice(6));
        } else if (line === '' && dataLines.length > 0) {
          // AI-08: Blank line = SSE frame boundary; join accumulated data lines
          try {
            const eventData = JSON.parse(dataLines.join('\n'));
            yield { event: eventType, data: eventData };
          } catch {
            // Skip malformed JSON
          }
          dataLines = [];
          eventType = 'message';
        }
      }
    }
    // Flush any remaining data lines at end of stream
    if (dataLines.length > 0) {
      try {
        const eventData = JSON.parse(dataLines.join('\n'));
        yield { event: eventType, data: eventData };
      } catch { /* skip */ }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function fetchColumnValues(
  datasetId: string,
  columnName: string,
  limit?: number,
): Promise<ColumnValuesResponse> {
  const params = limit ? `?limit=${limit}` : '';
  return apiFetch<ColumnValuesResponse>(
    `/datasets/${datasetId}/columns/${columnName}/values/${params}`,
  );
}

export async function fetchColumnStats(
  datasetId: string,
  columnName: string,
): Promise<ColumnStatsResponse> {
  return apiFetch<ColumnStatsResponse>(
    `/datasets/${datasetId}/columns/${columnName}/stats/`,
  );
}

function toChatLayers(layers: MapLayerResponse[]): ChatMapLayer[] {
  return layers.map((l) => ({
    id: l.id,
    name: l.display_name ?? l.dataset_name,
    dataset_id: l.dataset_id,
    dataset_table_name: l.dataset_table_name,
    geometry_type: l.dataset_geometry_type,
    layer_type: l.layer_type ?? null,
    column_info: l.dataset_column_info,
    visible: l.visible,
    filter: l.filter ?? null,
    label_config: l.label_config ?? null,
    popup_config: l.popup_config ?? null,
    style_config: l.style_config ?? null,
    paint: l.paint ?? null,
    dataset_title: l.dataset_name,
    feature_count: l.dataset_feature_count ?? null,
    sample_values: l.dataset_sample_values ?? null,
  }));
}

export async function sendChatMessage(
  mapId: string,
  message: string,
  layers: MapLayerResponse[],
  language?: string,
  history?: ChatHistoryMessage[],
): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/ai/chat/', {
    method: 'POST',
    body: JSON.stringify({
      message,
      map_id: mapId,
      layers: toChatLayers(layers),
      language,
      history,
    } satisfies ChatRequest),
  });
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export async function* streamChatMessage(
  mapId: string,
  message: string,
  layers: MapLayerResponse[],
  language?: string,
  history?: ChatHistoryMessage[],
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const chatLayers = toChatLayers(layers);

  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/ai/chat/stream/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      message,
      map_id: mapId,
      layers: chatLayers,
      language,
      history,
    }),
    signal,
  });

  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new ApiError(body || `Stream request failed: ${response.status}`, response.status);
  }

  if (!response.body) throw new Error('No response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = 'message';
  let dataLines: string[] = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const rawLines = buffer.split('\n');
      buffer = rawLines.pop() ?? '';

      for (const rawLine of rawLines) {
        // SSE spec allows \r\n, \n, or \r as line terminators. sse-starlette
        // uses \r\n, so after splitting on \n every line carries a trailing
        // \r that must be stripped before the empty-line frame boundary check.
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (line.startsWith('event: ')) {
          eventType = line.slice(7);
        } else if (line.startsWith('data: ')) {
          dataLines.push(line.slice(6));
        } else if (line === '' && dataLines.length > 0) {
          // AI-08: Blank line = SSE frame boundary; join accumulated data lines
          try {
            const data = JSON.parse(dataLines.join('\n'));
            yield { event: eventType, data };
          } catch {
            // Skip malformed JSON lines
          }
          dataLines = [];
          eventType = 'message';
        }
      }
    }
    // Flush any remaining data lines at end of stream
    if (dataLines.length > 0) {
      try {
        const data = JSON.parse(dataLines.join('\n'));
        yield { event: eventType, data };
      } catch { /* skip */ }
    }
  } finally {
    reader.releaseLock();
  }
}
