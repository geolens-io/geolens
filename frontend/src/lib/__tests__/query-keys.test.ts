import { queryKeys } from '@/lib/query-keys';

describe('queryKeys factory', () => {
  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------
  describe('auth', () => {
    it('me returns expected key', () => {
      expect(queryKeys.auth.me).toEqual(['auth', 'me']);
    });

    it('permissions returns expected key', () => {
      expect(queryKeys.auth.permissions).toEqual(['auth', 'permissions']);
    });

    it('all is a prefix of me', () => {
      const all = queryKeys.auth.all;
      expect(queryKeys.auth.me.slice(0, all.length)).toEqual([...all]);
    });
  });

  // -------------------------------------------------------------------------
  // Datasets
  // -------------------------------------------------------------------------
  describe('datasets', () => {
    it('all returns base key', () => {
      expect(queryKeys.datasets.all).toEqual(['datasets']);
    });

    it('detail includes id', () => {
      expect(queryKeys.datasets.detail('abc')).toEqual(['dataset', 'abc']);
    });

    it('rows includes all params', () => {
      expect(queryKeys.datasets.rows('abc', 50, 0)).toEqual(['dataset-rows', 'abc', 50, 0, undefined]);
      const filters = { name: 'x' };
      expect(queryKeys.datasets.rows('abc', 50, 0, filters)).toEqual(['dataset-rows', 'abc', 50, 0, filters]);
    });

    it('history includes skip and limit', () => {
      expect(queryKeys.datasets.history('abc', 0, 50)).toEqual(['dataset-history', 'abc', 0, 50]);
    });

    it('versions includes skip and limit', () => {
      expect(queryKeys.datasets.versions('abc', 0, 50)).toEqual(['dataset-versions', 'abc', 0, 50]);
    });

    it('attributes includes datasetId', () => {
      expect(queryKeys.datasets.attributes('abc')).toEqual(['attributes', 'abc']);
    });

    it('validation includes datasetId', () => {
      expect(queryKeys.datasets.validation('abc')).toEqual(['validation', 'abc']);
    });

    it('related is a superset of all', () => {
      const key = queryKeys.datasets.related('abc');
      expect(key[0]).toBe('datasets');
    });

    it('maps is a superset of all', () => {
      const key = queryKeys.datasets.maps('abc');
      expect(key[0]).toBe('datasets');
    });

    it('quicklook includes datasetId', () => {
      expect(queryKeys.datasets.quicklook('abc')).toEqual(['dataset-quicklook', 'abc']);
    });

    it('rowsPrefix is a prefix of rows', () => {
      const prefix = queryKeys.datasets.rowsPrefix('abc');
      const full = queryKeys.datasets.rows('abc', 50, 0);
      expect(full.slice(0, prefix.length)).toEqual([...prefix]);
    });
  });

  // -------------------------------------------------------------------------
  // Maps
  // -------------------------------------------------------------------------
  describe('maps', () => {
    it('all returns base key', () => {
      expect(queryKeys.maps.all).toEqual(['maps']);
    });

    it('list is a superset of all', () => {
      const params = { skip: 0, limit: 20 };
      const key = queryKeys.maps.list(params);
      expect(key[0]).toBe('maps');
    });

    it('detail includes id', () => {
      expect(queryKeys.maps.detail('abc')).toEqual(['map', 'abc']);
    });

    it('shareToken includes mapId', () => {
      expect(queryKeys.maps.shareToken('abc')).toEqual(['map-share-token', 'abc']);
    });

    it('embedTokens includes mapId', () => {
      expect(queryKeys.maps.embedTokens('abc')).toEqual(['map-embed-tokens', 'abc']);
    });

    it('sharedMap includes token', () => {
      expect(queryKeys.maps.sharedMap('tok123')).toEqual(['shared-map', 'tok123', undefined]);
      expect(queryKeys.maps.sharedMap('tok123', 'key')).toEqual(['shared-map', 'tok123', 'key']);
    });

    it('columnValues includes datasetId and col', () => {
      expect(queryKeys.maps.columnValues('abc', 'name')).toEqual(['column-values', 'abc', 'name']);
    });

    it('columnStats includes datasetId and col', () => {
      expect(queryKeys.maps.columnStats('abc', 'name')).toEqual(['column-stats', 'abc', 'name']);
    });
  });

  // -------------------------------------------------------------------------
  // Collections
  // -------------------------------------------------------------------------
  describe('collections', () => {
    it('all returns base key', () => {
      expect(queryKeys.collections.all).toEqual(['collections']);
    });

    it('list is a superset of all', () => {
      const key = queryKeys.collections.list(0, 50);
      expect(key[0]).toBe('collections');
    });

    it('detail includes id', () => {
      expect(queryKeys.collections.detail('abc')).toEqual(['collection', 'abc']);
    });

    it('datasets includes collectionId', () => {
      expect(queryKeys.collections.datasets('abc', 0, 20)).toEqual(['collection-datasets', 'abc', 0, 20]);
    });

    it('datasetsPrefix is a prefix of datasets', () => {
      const prefix = queryKeys.collections.datasetsPrefix('abc');
      const full = queryKeys.collections.datasets('abc', 0, 20);
      expect(full.slice(0, prefix.length)).toEqual([...prefix]);
    });
  });

  // -------------------------------------------------------------------------
  // Search
  // -------------------------------------------------------------------------
  describe('search', () => {
    it('results includes params', () => {
      const params = { q: 'test' };
      expect(queryKeys.search.results(params)).toEqual(['search', params]);
    });

    it('facets includes params', () => {
      const params = { q: 'test' };
      expect(queryKeys.search.facets(params)).toEqual(['facets', params]);
    });

    it('summary returns expected key', () => {
      expect(queryKeys.search.summary).toEqual(['catalog-summary']);
    });
  });

  // -------------------------------------------------------------------------
  // Admin
  // -------------------------------------------------------------------------
  describe('admin', () => {
    it('all returns base key', () => {
      expect(queryKeys.admin.all).toEqual(['admin']);
    });

    it('stats is a superset of all', () => {
      expect(queryKeys.admin.stats[0]).toBe('admin');
    });

    it('users includes skip, limit, status, search', () => {
      expect(queryKeys.admin.users(0, 50)).toEqual(['admin', 'users', 0, 50, undefined, undefined]);
      expect(queryKeys.admin.users(0, 50, 'active', 'bob')).toEqual(['admin', 'users', 0, 50, 'active', 'bob']);
    });

    it('aiStatus returns expected key', () => {
      expect(queryKeys.admin.aiStatus).toEqual(['admin', 'ai-status']);
    });

    it('embeddingStats returns expected key', () => {
      expect(queryKeys.admin.embeddingStats).toEqual(['admin', 'embedding-stats']);
    });

    it('infrastructure returns expected key', () => {
      expect(queryKeys.admin.infrastructure).toEqual(['admin', 'infrastructure']);
    });
  });

  // -------------------------------------------------------------------------
  // Settings
  // -------------------------------------------------------------------------
  describe('settings', () => {
    it('all returns base key', () => {
      expect(queryKeys.settings.all).toEqual(['settings']);
    });

    it('basemaps is a superset of all', () => {
      expect(queryKeys.settings.basemaps[0]).toBe('settings');
    });

    it('branding returns expected key', () => {
      expect(queryKeys.settings.branding).toEqual(['settings', 'branding']);
    });
  });

  // -------------------------------------------------------------------------
  // Ingest
  // -------------------------------------------------------------------------
  describe('ingest', () => {
    it('jobStatus includes jobId', () => {
      expect(queryKeys.ingest.jobStatus('job123')).toEqual(['job-status', 'job123']);
    });

    it('discoverTables returns expected key', () => {
      expect(queryKeys.ingest.discoverTables).toEqual(['discover-tables']);
    });

    it('uploadConfig returns expected key', () => {
      expect(queryKeys.ingest.uploadConfig).toEqual(['upload-config']);
    });
  });

  // -------------------------------------------------------------------------
  // Saved searches
  // -------------------------------------------------------------------------
  describe('savedSearches', () => {
    it('all returns expected key', () => {
      expect(queryKeys.savedSearches.all).toEqual(['saved-searches']);
    });
  });

  // -------------------------------------------------------------------------
  // API keys
  // -------------------------------------------------------------------------
  describe('apiKeys', () => {
    it('mine returns expected key', () => {
      expect(queryKeys.apiKeys.mine).toEqual(['my-api-keys']);
    });
  });

  // -------------------------------------------------------------------------
  // Tile tokens
  // -------------------------------------------------------------------------
  describe('tileTokens', () => {
    it('token includes datasetId', () => {
      expect(queryKeys.tileTokens.token('abc')).toEqual(['tile-token', 'abc']);
    });
  });

  // -------------------------------------------------------------------------
  // VRT
  // -------------------------------------------------------------------------
  describe('vrt', () => {
    it('sources includes datasetId', () => {
      expect(queryKeys.vrt.sources('abc')).toEqual(['vrt-sources', 'abc']);
    });

    it('status includes datasetId', () => {
      expect(queryKeys.vrt.status('abc')).toEqual(['vrt-status', 'abc']);
    });

    it('generations includes datasetId and optional params', () => {
      expect(queryKeys.vrt.generations('abc')).toEqual(['vrt-generations', 'abc', undefined]);
      expect(queryKeys.vrt.generations('abc', { limit: 10 })).toEqual(['vrt-generations', 'abc', { limit: 10 }]);
    });
  });

  // -------------------------------------------------------------------------
  // Edition
  // -------------------------------------------------------------------------
  describe('edition', () => {
    it('info returns expected key', () => {
      expect(queryKeys.edition.info).toEqual(['edition']);
    });
  });
});
