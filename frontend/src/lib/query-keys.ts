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

import type { AggregateRequest } from '@/api/aggregate';
import type { DatasetRowsSort } from '@/api/datasets';
import type { MapBrowseParams } from '@/types/api';

export const queryKeys = {
  auth: {
    all: ['auth'] as const,
    me: ['auth', 'me'] as const,
    permissions: ['auth', 'permissions'] as const,
    // Scoped by user id so a store-only logout (e.g. failed refresh) followed
    // by a different login can't render the prior user's cached usage.
    usage: (userId: string | undefined) => ['auth', 'me', 'usage', userId] as const,
  },

  groups: {
    mine: ['groups', 'mine'] as const,
  },
  datasets: {
    all: ['datasets'] as const,
    detail: (id: string) => ['dataset', id] as const,
    rows: (
      id: string,
      limit: number,
      cursor: number,
      filters?: Record<string, string>,
      sort?: DatasetRowsSort,
      cql2Filter?: string,
    ) => ['dataset-rows', id, limit, cursor, filters, sort, cql2Filter] as const,
    rowsPrefix: (id: string) => ['dataset-rows', id] as const,
    history: (id: string, skip: number, limit: number) =>
      ['dataset-history', id, skip, limit] as const,
    versions: (id: string, skip: number, limit: number) =>
      ['dataset-versions', id, skip, limit] as const,
    versionsPrefix: (id: string) => ['dataset-versions', id] as const,
    refreshRuns: (id: string, skip: number, limit: number) =>
      ['dataset-refresh-runs', id, skip, limit] as const,
    refreshRunsPrefix: (id: string) => ['dataset-refresh-runs', id] as const,
    sync: (id: string) => ['dataset-sync', id] as const,
    syncCredentialsPrefix: ['sync-credentials'] as const,
    syncCredentials: (datasetId: string) => ['sync-credentials', datasetId] as const,
    attributes: (id: string | undefined) => ['attributes', id] as const,
    validation: (id: string | undefined) => ['validation', id] as const,
    related: (id: string) => ['datasets', id, 'related'] as const,
    maps: (id: string) => ['datasets', id, 'maps'] as const,
  },

  stories: {
    all: ['stories'] as const,
    list: (params: { skip: number; limit: number }) => ['stories', params] as const,
    detail: (id: string | undefined) => ['story', id] as const,
    draft: (id: string | undefined) => ['story', id, 'draft'] as const,
    /** Under its own root, which blob-url-cache revokes. */
    image: (path: string) => ['asset-image', path] as const,
  },

  maps: {
    all: ['maps'] as const,
    list: (params: MapBrowseParams) => ['maps', params] as const,
    // Under the maps root, so whatever refreshes map lists refreshes the story map picker.
    picker: (search: string) => ['maps', 'picker', search] as const,
    detail: (id: string | undefined) => ['map', id] as const,
    // Prefix of every map's detail key and the keys under it.
    detailRoot: ['map'] as const,
    // Under the detail key, so whatever refetches the map refetches its gaps.
    groupGaps: (id: string | undefined) => ['map', id, 'group-gaps'] as const,
    access: (id: string | undefined) => ['map-access', id] as const,
    stories: (id: string | undefined) => ['map', id, 'stories'] as const,
    history: (mapId: string | undefined, skip: number, limit: number) =>
      ['map-history', mapId, skip, limit] as const,
    historyPrefix: (mapId: string | undefined) => ['map-history', mapId] as const,
    // Public-safe AI readiness signal for non-admin editors.
    aiAvailability: ['ai-availability'] as const,
    shareToken: (mapId: string | undefined) => ['map-share-token', mapId] as const,
    embedTokens: (mapId: string | undefined) => ['map-embed-tokens', mapId] as const,
    sharedMap: (token: string | undefined, embedToken?: string) =>
      ['shared-map', token, embedToken] as const,
    columnValues: (datasetId: string | undefined, col: string | undefined) =>
      ['column-values', datasetId, col] as const,
    columnValuesPrefix: (datasetId: string) => ['column-values', datasetId] as const,
    columnStats: (datasetId: string | undefined, col: string | undefined) =>
      ['column-stats', datasetId, col] as const,
    columnStatsPrefix: (datasetId: string) => ['column-stats', datasetId] as const,
  },

  /**
   * Keep the icon list outside `maps.all` so map mutations do not refetch the
   * instance-wide sprite catalog.
   */
  mapIcons: {
    all: ['map-icons'] as const,
  },

  collections: {
    all: ['collections'] as const,
    list: (skip: number, limit: number) => ['collections', skip, limit] as const,
    detail: (id: string) => ['collection', id] as const,
    datasets: (collectionId: string, skip: number, limit: number) =>
      ['collection-datasets', collectionId, skip, limit] as const,
    datasetsPrefix: (collectionId: string) => ['collection-datasets', collectionId] as const,
  },

  search: {
    all: ['search'] as const,
    results: (params: Record<string, string>) => ['search', params] as const,
    facets: (params: Record<string, string>) => ['facets', params] as const,
    summary: ['catalog-summary'] as const,
    // Parallel maps lookup driven by the same `q` as the dataset catalog search.
    maps: (q: string) => ['search', 'maps', q] as const,
  },

  records: {
    contacts: (recordId: string | undefined) => ['contacts', recordId] as const,
    keywords: (recordId: string | undefined) => ['keywords', recordId] as const,
    distributions: (recordId: string | undefined) => ['distributions', recordId] as const,
    validation: ['validation'] as const,
  },

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
      role?: string,
    ) => ['admin', 'users', skip, limit, status, search, sort, order, role] as const,
    userNames: ['admin', 'users', 'names'] as const,
    groups: (skip: number, limit: number) => ['admin', 'groups', skip, limit] as const,
    allGroups: ['admin', 'groups'] as const,
    groupMembers: (groupId: string) => ['admin', 'groups', 'members', groupId] as const,
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
    // different responses. The jobs/auditLogs keys take the whole params
    // object, so they carry sort/order already.
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
    // pageIndex makes each page its own cache entry; invalidating the bare
    // [admin, api-keys, userId] prefix still hits every loaded page.
    apiKeys: (userId: string, pageIndex?: number) =>
      pageIndex === undefined
        ? (['admin', 'api-keys', userId] as const)
        : (['admin', 'api-keys', userId, pageIndex] as const),
    embeddingStats: ['admin', 'embedding-stats'] as const,
    infrastructure: ['admin', 'infrastructure'] as const,
  },

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
    // Server-driven enterprise-only Settings tab list.
    enterpriseTabs: ['settings', 'enterprise-tabs'] as const,
    // Notification channel status contains booleans only.
    notificationStatus: ['settings', 'notification-status'] as const,
  },

  ingest: {
    jobStatus: (jobId: string | null) => ['job-status', jobId] as const,
    jobStatusByDataset: (datasetId: string | null) =>
      ['job-status-by-dataset', datasetId] as const,
    discoverTables: ['discover-tables'] as const,
    uploadConfig: ['upload-config'] as const,
  },

  savedSearches: {
    all: ['saved-searches'] as const,
  },

  apiKeys: {
    mine: ['my-api-keys'] as const,
    dataset: (datasetId: string) => ['dataset-api-keys', datasetId] as const,
  },

  dashboard: {
    // `auth` is the embed token, as in tileTokens.viewerBatch, so an aggregate
    // one token authorized is never served to a viewer without it. `version`
    // is the dataset's tile version, so a refreshed dataset asks again.
    aggregate: (datasetId: string, version: string | number | null, body: AggregateRequest | null, auth: string) =>
      ['dashboard-aggregate', datasetId, version, body, auth] as const,
    aggregatePrefix: (datasetId: string) => ['dashboard-aggregate', datasetId] as const,
  },

  tileTokens: {
    token: (datasetId: string | undefined) => ['tile-token', datasetId] as const,
    batch: (sortedIds: string) => ['tile-tokens-batch', sortedIds] as const,
    // The viewer batch is separate because it mints with an embed token
    // instead of the session JWT; sharing one entry would serve a viewer tokens
    // minted for someone else's scope. `auth` is the discriminator, and it
    // stays out of bug reports because main.tsx's reportQueryKey serializes
    // only the leading namespace segment. Keeping 'tile-tokens-batch' first
    // puts these under useInvalidateTileTokens' sweep (WebGL context restore).
    viewerBatch: (sortedIds: string, auth: string) =>
      ['tile-tokens-batch', 'viewer', sortedIds, auth] as const,
  },

  vrt: {
    sources: (datasetId: string) => ['vrt-sources', datasetId] as const,
    status: (datasetId: string) => ['vrt-status', datasetId] as const,
    generations: (datasetId: string, params?: { limit?: number; offset?: number }) =>
      ['vrt-generations', datasetId, params] as const,
  },

  edition: {
    info: ['edition'] as const,
  },

  authConfig: {
    config: ['auth', 'config'] as const,
    oauthProviders: ['auth', 'oauth-providers'] as const,
  },

  settingsOAuth: {
    providers: ['settings', 'oauth-providers'] as const,
  },

  /**
   * Own root rather than under `settingsOAuth`: `listSamlProviders` fetches the
   * same `/settings/oauth-providers/` endpoint but filters it to the SAML rows,
   * so the two caches hold different payloads and must not prefix-match.
   * `useInvalidateAuthProviders` fans a provider mutation out across both.
   */
  saml: {
    providers: ['saml', 'providers'] as const,
  },

  relationships: {
    list: (datasetId: string) => ['dataset-relationships', datasetId] as const,
    // A list's broken flags also depend on each target dataset's schema.
    listPrefix: ['dataset-relationships'] as const,
    records: (datasetId: string, featureGid: number, relationshipId: string) =>
      ['related-records', datasetId, featureGid, relationshipId] as const,
    // records() is parameterized by featureGid and relationshipId, which a
    // dataset-level sweep lacks; this prefix invalidates every cached
    // related-record entry for the dataset.
    recordsPrefix: (datasetId: string) => ['related-records', datasetId] as const,
  },

  ogcRecords: {
    detail: (id: string) => ['ogc-record', id] as const,
  },

  cogSearch: {
    results: (query: string) => ['cog-search', query] as const,
    addSource: (query: string) => ['cog-search-add-source', query] as const,
  },

  datasetSearch: {
    all: ['dataset-search'] as const,
    results: (query: string, recordType: string) =>
      ['dataset-search', query, recordType] as const,
  },

  typeahead: {
    results: (query: string) => ['typeahead', query] as const,
  },
} as const;
