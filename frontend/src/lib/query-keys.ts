/**
 * Centralized query key factory.
 *
 * All TanStack Query keys should be defined here. Use these factories in
 * `queryKey`, `invalidateQueries`, and `getQueryData` calls.
 *
 * Design rules:
 * - Each domain has an `all` key for list/browse invalidation.
 *   Note: `all` only prefix-matches queries whose keys share the same root
 *   string. Some domains use different roots for list vs detail (e.g.
 *   `datasets.all` = `['datasets']` but `datasets.detail(id)` = `['dataset', id]`).
 * - Parameterized keys extend their respective root:
 *   `queryKeys.datasets.detail(id)` returns `['dataset', id]`.
 * - Key strings match existing cache entries exactly to avoid cache misses
 *   during deployment.
 */

import type { MapBrowseParams } from '@/types/api';

export const queryKeys = {
  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------
  auth: {
    all: ['auth'] as const,
    me: ['auth', 'me'] as const,
    permissions: ['auth', 'permissions'] as const,
  },

  // -------------------------------------------------------------------------
  // Datasets
  // -------------------------------------------------------------------------
  datasets: {
    all: ['datasets'] as const,
    detail: (id: string) => ['dataset', id] as const,
    rows: (id: string, limit: number, cursor: number, filters?: Record<string, string>) =>
      ['dataset-rows', id, limit, cursor, filters] as const,
    rowsPrefix: (id: string) => ['dataset-rows', id] as const,
    history: (id: string, skip: number, limit: number) =>
      ['dataset-history', id, skip, limit] as const,
    versions: (id: string, skip: number, limit: number) =>
      ['dataset-versions', id, skip, limit] as const,
    versionsPrefix: (id: string) => ['dataset-versions', id] as const,
    attributes: (id: string | undefined) => ['attributes', id] as const,
    validation: (id: string | undefined) => ['validation', id] as const,
    related: (id: string) => ['datasets', id, 'related'] as const,
    maps: (id: string) => ['datasets', id, 'maps'] as const,
  },

  // -------------------------------------------------------------------------
  // Maps
  // -------------------------------------------------------------------------
  maps: {
    all: ['maps'] as const,
    list: (params: MapBrowseParams) => ['maps', params] as const,
    detail: (id: string | undefined) => ['map', id] as const,
    shareToken: (mapId: string | undefined) => ['map-share-token', mapId] as const,
    embedTokens: (mapId: string | undefined) => ['map-embed-tokens', mapId] as const,
    sharedMap: (token: string | undefined, apiKey?: string) =>
      ['shared-map', token, apiKey] as const,
    columnValues: (datasetId: string | undefined, col: string | undefined) =>
      ['column-values', datasetId, col] as const,
    columnStats: (datasetId: string | undefined, col: string | undefined) =>
      ['column-stats', datasetId, col] as const,
  },

  // -------------------------------------------------------------------------
  // Collections
  // -------------------------------------------------------------------------
  collections: {
    all: ['collections'] as const,
    list: (skip: number, limit: number) => ['collections', skip, limit] as const,
    detail: (id: string) => ['collection', id] as const,
    datasets: (collectionId: string, skip: number, limit: number) =>
      ['collection-datasets', collectionId, skip, limit] as const,
    datasetsPrefix: (collectionId: string) => ['collection-datasets', collectionId] as const,
  },

  // -------------------------------------------------------------------------
  // Search
  // -------------------------------------------------------------------------
  search: {
    all: ['search'] as const,
    results: (params: Record<string, string>) => ['search', params] as const,
    facets: (params: Record<string, string>) => ['facets', params] as const,
    summary: ['catalog-summary'] as const,
  },

  // -------------------------------------------------------------------------
  // Records (contacts, keywords, distributions)
  // -------------------------------------------------------------------------
  records: {
    contacts: (recordId: string | undefined) => ['contacts', recordId] as const,
    keywords: (recordId: string | undefined) => ['keywords', recordId] as const,
    distributions: (recordId: string | undefined) => ['distributions', recordId] as const,
    validation: ['validation'] as const,
  },

  // -------------------------------------------------------------------------
  // Admin
  // -------------------------------------------------------------------------
  admin: {
    all: ['admin'] as const,
    stats: ['admin', 'stats'] as const,
    users: (skip: number, limit: number, status?: string, search?: string) =>
      ['admin', 'users', skip, limit, status, search] as const,
    userNames: ['admin', 'users', 'names'] as const,
    pendingCount: ['admin', 'users', 'pending-count'] as const,
    allUsers: ['admin', 'users'] as const,
    auditLogs: (params: Record<string, unknown>) => ['admin', 'audit-logs', params] as const,
    jobs: (params: Record<string, unknown>) => ['admin', 'jobs', params] as const,
    allJobs: ['admin', 'jobs'] as const,
    failedJobCount: ['admin', 'jobs', 'failed-count'] as const,
    aiStatus: ['admin', 'ai-status'] as const,
    shareTokens: (skip: number, limit: number, search?: string, status?: string) =>
      ['admin', 'share-tokens', skip, limit, search, status] as const,
    allShareTokens: ['admin', 'share-tokens'] as const,
    embedTokens: (params: Record<string, unknown>) => ['admin', 'embed-tokens', params] as const,
    allEmbedTokens: ['admin', 'embed-tokens'] as const,
    apiKeys: (userId: string) => ['admin', 'api-keys', userId] as const,
    embeddingStats: ['admin', 'embedding-stats'] as const,
    infrastructure: ['admin', 'infrastructure'] as const,
  },

  // -------------------------------------------------------------------------
  // Settings
  // -------------------------------------------------------------------------
  settings: {
    all: ['settings'] as const,
    basemaps: ['settings', 'basemaps'] as const,
    mapDefaults: ['settings', 'map-defaults'] as const,
    tileConfig: ['settings', 'tile-config'] as const,
    enabledWidgets: ['settings', 'enabled-widgets'] as const,
    featureFlags: ['settings', 'feature-flags'] as const,
    allSettings: ['settings', 'all'] as const,
    configMode: ['settings', 'config-mode'] as const,
    apiKeyStatus: ['settings', 'api-key-status'] as const,
    branding: ['settings', 'branding'] as const,
  },

  // -------------------------------------------------------------------------
  // Ingest
  // -------------------------------------------------------------------------
  ingest: {
    jobStatus: (jobId: string | null) => ['job-status', jobId] as const,
    jobStatusByDataset: (datasetId: string | null) =>
      ['job-status-by-dataset', datasetId] as const,
    discoverTables: ['discover-tables'] as const,
    uploadConfig: ['upload-config'] as const,
  },

  // -------------------------------------------------------------------------
  // Saved searches
  // -------------------------------------------------------------------------
  savedSearches: {
    all: ['saved-searches'] as const,
  },

  // -------------------------------------------------------------------------
  // User API keys
  // -------------------------------------------------------------------------
  apiKeys: {
    mine: ['my-api-keys'] as const,
  },

  // -------------------------------------------------------------------------
  // Tile tokens
  // -------------------------------------------------------------------------
  tileTokens: {
    token: (datasetId: string | undefined) => ['tile-token', datasetId] as const,
    batch: (sortedIds: string) => ['tile-tokens-batch', sortedIds] as const,
  },

  // -------------------------------------------------------------------------
  // VRT
  // -------------------------------------------------------------------------
  vrt: {
    sources: (datasetId: string) => ['vrt-sources', datasetId] as const,
    status: (datasetId: string) => ['vrt-status', datasetId] as const,
    generations: (datasetId: string, params?: { limit?: number; offset?: number }) =>
      ['vrt-generations', datasetId, params] as const,
  },

  // -------------------------------------------------------------------------
  // Edition
  // -------------------------------------------------------------------------
  edition: {
    info: ['edition'] as const,
  },

  // -------------------------------------------------------------------------
  // Auth config & OAuth
  // -------------------------------------------------------------------------
  authConfig: {
    config: ['auth', 'config'] as const,
    oauthProviders: ['auth', 'oauth-providers'] as const,
  },

  // -------------------------------------------------------------------------
  // Settings OAuth
  // -------------------------------------------------------------------------
  settingsOAuth: {
    providers: ['settings', 'oauth-providers'] as const,
  },

  // -------------------------------------------------------------------------
  // Relationships
  // -------------------------------------------------------------------------
  relationships: {
    list: (datasetId: string) => ['dataset-relationships', datasetId] as const,
    records: (datasetId: string, featureGid: number, relationshipId: string) =>
      ['related-records', datasetId, featureGid, relationshipId] as const,
  },

  // -------------------------------------------------------------------------
  // OGC records
  // -------------------------------------------------------------------------
  ogcRecords: {
    detail: (id: string) => ['ogc-record', id] as const,
  },

  // -------------------------------------------------------------------------
  // COG / dataset search (builder & VRT)
  // -------------------------------------------------------------------------
  cogSearch: {
    results: (query: string) => ['cog-search', query] as const,
    addSource: (query: string) => ['cog-search-add-source', query] as const,
  },

  // -------------------------------------------------------------------------
  // Dataset search (builder panel)
  // -------------------------------------------------------------------------
  datasetSearch: {
    results: (query: string, recordType: string) =>
      ['dataset-search', query, recordType] as const,
  },

  // -------------------------------------------------------------------------
  // Typeahead
  // -------------------------------------------------------------------------
  typeahead: {
    results: (query: string) => ['typeahead', query] as const,
  },
} as const;
