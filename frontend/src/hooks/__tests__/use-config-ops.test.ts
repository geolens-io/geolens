import { QueryClient } from '@tanstack/react-query';
import { renderHook } from '@/test/test-utils';
import { importConfig } from '@/api/config-ops';
import { useImportConfig } from '@/hooks/use-config-ops';
import { queryKeys } from '@/lib/query-keys';

vi.mock('@/api/config-ops', () => ({
  exportConfig: vi.fn(),
  dryRunImport: vi.fn(),
  importConfig: vi.fn(),
  validateConnectivity: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockImportConfig = vi.mocked(importConfig);

describe('useImportConfig', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it('invalidates settings, auth, and AI status caches after a successful import', async () => {
    const invalidateQueries = vi
      .spyOn(QueryClient.prototype, 'invalidateQueries')
      .mockResolvedValue(undefined);
    mockImportConfig.mockResolvedValueOnce({
      settings_applied: 1,
      settings_skipped: 0,
      oauth_created: 1,
      oauth_updated: 0,
      oauth_deleted: 0,
      oauth_accounts_deleted: 0,
    });
    const { result } = renderHook(() => useImportConfig());

    await result.current.mutateAsync({
      data: { settings: { registration_enabled: true } },
      mode: 'merge',
    });

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.settings.all,
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.authConfig.config,
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.authConfig.oauthProviders,
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.admin.aiStatus,
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.maps.aiAvailability,
    });
  });

  it('does not invalidate caches when the import fails', async () => {
    const invalidateQueries = vi
      .spyOn(QueryClient.prototype, 'invalidateQueries')
      .mockResolvedValue(undefined);
    mockImportConfig.mockRejectedValueOnce(new Error('Import failed'));
    const { result } = renderHook(() => useImportConfig());

    await expect(
      result.current.mutateAsync({ data: { settings: {} }, mode: 'merge' }),
    ).rejects.toThrow('Import failed');

    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it('forwards the bound overwrite preview token', async () => {
    mockImportConfig.mockResolvedValueOnce({
      settings_applied: 1,
      settings_skipped: 0,
      oauth_created: 0,
      oauth_updated: 0,
      oauth_deleted: 0,
      oauth_accounts_deleted: 0,
    });
    const { result } = renderHook(() => useImportConfig());

    await result.current.mutateAsync({
      data: { settings: { log_level: 'DEBUG' } },
      mode: 'overwrite',
      previewToken: 'signed-preview',
    });

    expect(mockImportConfig).toHaveBeenCalledWith(
      { settings: { log_level: 'DEBUG' } },
      'overwrite',
      'signed-preview',
    );
  });
});
