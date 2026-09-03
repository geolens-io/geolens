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
    // Scoped by user id so a store-only logout (e.g. failed-refresh in
    // api/client.ts) followed by a different login can't render the prior
    // user's cached usage.
    usage: (userId: string | undefined) => ['auth', 'me', 'usage', userId] as const,
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
    refreshRuns: (id: string, skip: number, limit: number) =>
      ['dataset-refresh-runs', id, skip, limit] as const,
    refreshRunsPrefix: (id: string) => ['dataset-refresh-runs', id] as const,
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
    access: (id: string | undefined) => ['map-access', id] as const,
    history: (mapId: string | undefined, skip: number, limit: number) =>
      ['map-history', mapId, skip, limit] as const,
    historyPrefix: (mapId: string | undefined) => ['map-history', mapId] as const,
    // builder-audit #338 P1-11: public-safe AI readiness signal for non-admin editors.
    aiAvailability: ['ai-availability'] as const,
    shareToken: (mapId: string | undefined) => ['map-share-token', mapId] as const,
    embedTokens: (mapId: string | undefined) => ['map-embed-tokens', mapId] as const,
    sharedMap: (token: string | undefined, apiKey?: string, embedToken?: string) =>
      ['shared-map', token, apiKey, embedToken] as const,
    columnValues: (datasetId: string | undefined, col: string | undefined) =>
      ['column-values', datasetId, col] as const,
    columnValuesPrefix: (datasetId: string) => ['column-values', datasetId] as const,
    columnStats: (datasetId: string | undefined, col: string | undefined) =>
      ['column-stats', datasetId, col] as const,
    columnStatsPrefix: (datasetId: string) => ['column-stats', datasetId] as const,
  },

  /**
   * fix(#438): DATA-06 — the icon list used a bare inline `['maps', 'icons']`,
   * which sits under the `maps.all` prefix. Every map mutation invalidates
   * `maps.all`, so the sprite catalog refetched on every save, rename, and
   * visibility toggle. It is not map-scoped data; it gets its own root.
   */
  mapIcons: {
    all: ['map-icons'] as const,
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
    // fix(#430 V-08): parallel maps lookup driven by the same `q` as the dataset
    // catalog search — see useMapSearchResults in components/search/hooks/use-search.ts.
    maps: (q: string) => ['search', 'maps', q] as const,
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
    // sort/order belong in the key: two orderings of the same page are
    // different responses, and sharing a key would serve one for the other.
    users: (
      skip: number,
      limit: number,
      status?: string,
      search?: string,
      sort?: string,
      order?: string,
    ) => ['admin', 'users', skip, limit, status, search, sort, order] as const,
    userNames: ['admin', 'users', 'names'] as const,
    pendingCount: ['admin', 'users', 'pending-count'] as const,
    allUsers: ['admin', 'users'] as const,
    auditLogs: (params: Record<string, unknown>) => ['admin', 'audit-logs', params] as const,
    jobs: (params: Record<string, unknown>) => ['admin', 'jobs', params] as const,
    allJobs: ['admin', 'jobs'] as const,
    failedJobCount: ['admin', 'jobs', 'failed-count'] as const,
    userCount: ['admin', 'users', 'count'] as const,
    publishedMapCount: ['admin', 'share-tokens', 'count'] as const,
    auditLogCount: ['admin', 'audit-logs', 'count'] as const,
    aiStatus: ['admin', 'ai-status'] as const,
    // sort/order belong in the key: two orderings of the same page are
    // different responses, and sharing a key would serve one for the other.
    // The jobs/auditLogs keys take the whole params object, so they carry
    // sort/order without a signature change.
    shareTokens: (
      skip: number,
      limit: number,
      search?: string,
      status?: string,
      sort?: string,
      order?: string,
    ) => ['admin', 'share-tokens', skip, limit, search, status, sort, order] as const,
    allShareTokens: ['admin', 'share-tokens'] as const,
    embedTokens: (params: Record<string, unknown>) => ['admin', 'embed-tokens', params] as const,
    allEmbedTokens: ['admin', 'embed-tokens'] as const,
    // fix(#1805 review round 3 P2): pageIndex makes each page its own
    // cache entry so a create/revoke mutation's invalidateQueries on the
    // bare [admin, api-keys, userId] prefix still hits every loaded page.
    apiKeys: (userId: string, pageIndex?: number) =>
      pageIndex === undefined
        ? (['admin', 'api-keys', userId] as const)
        : (['admin', 'api-keys', userId, pageIndex] as const),
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
    enabledPlugins: ['settings', 'enabled-plugins'] as const,
    featureFlags: ['settings', 'feature-flags'] as const,
    allSettings: ['settings', 'all'] as const,
    configMode: ['settings', 'config-mode'] as const,
    apiKeyStatus: ['settings', 'api-key-status'] as const,
    branding: ['settings', 'branding'] as const,
    // Phase 279 ADMIN-03 (M-03): server-driven enterprise-only Settings-tab list.
    enterpriseTabs: ['settings', 'enterprise-tabs'] as const,
    // Phase 1229 Plan 03 (NOTIF-06): notification channel status (booleans only).
    notificationStatus: ['settings', 'notification-status'] as const,
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
    // fix(#890): the viewer's batch. Separate from `batch` because the viewer
    // mints with an API key / embed token instead of the session JWT, and those
    // grants scope differently — sharing one cache entry would serve a viewer
    // tokens minted for someone else's scope. `auth` is that discriminator, and
    // it stays out of bug reports because main.tsx's reportQueryKey serializes
    // only the leading namespace segment. Keeping 'tile-tokens-batch' first also
    // puts these under useInvalidateTileTokens' sweep (WebGL context restore).
    viewerBatch: (sortedIds: string, auth: string) =>
      ['tile-tokens-batch', 'viewer', sortedIds, auth] as const,
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
  // SAML providers
  // -------------------------------------------------------------------------
  /**
   * fix(#1164): the admin SAML section read and invalidated its list through four
   * independent `['saml', 'providers']` literals that agreed only by convention.
   * A typo in any one of them produced an invalidation that silently did nothing.
   * The key string is unchanged so existing cache entries still match (see the
   * deployment rule at the top of this file).
   *
   * This gets its own root rather than sitting under `settingsOAuth` even though
   * `listSamlProviders` (api/saml.ts) fetches the same `/settings/oauth-providers/`
   * endpoint: it filters the response down to the SAML rows, so the two caches hold
   * different payloads and must not prefix-match each other. Fanning a provider
   * mutation out across both is `useInvalidateAuthProviders`
   * (hooks/use-auth-providers.ts), which the SAML section calls alongside this key.
   */
  saml: {
    providers: ['saml', 'providers'] as const,
  },

  // -------------------------------------------------------------------------
  // Relationships
  // -------------------------------------------------------------------------
  relationships: {
    list: (datasetId: string) => ['dataset-relationships', datasetId] as const,
    records: (datasetId: string, featureGid: number, relationshipId: string) =>
      ['related-records', datasetId, featureGid, relationshipId] as const,
    // fix(#1285 codex round 5): records() is parameterized by featureGid and
    // relationshipId, neither of which a dataset-level cache sweep has — this
    // is the prefix that invalidates every cached related-record entry for
    // the dataset regardless of which feature/relationship it was fetched for.
    recordsPrefix: (datasetId: string) => ['related-records', datasetId] as const,
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
