import { renderHook, act } from '@testing-library/react';
import { useHeroState } from '@/hooks/use-hero-state';

describe('useHeroState', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts in loading state for raster datasets', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );
    expect(result.current.heroState).toBe('loading');
    expect(result.current.isRasterOrVrt).toBe(true);
  });

  it('starts in loading state for VRT datasets', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'vrt_dataset', hasTileUrl: true }),
    );
    expect(result.current.isRasterOrVrt).toBe(true);
    expect(result.current.heroState).toBe('loading');
  });

  it('is not rasterOrVrt for vector datasets', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'vector_dataset', hasTileUrl: false }),
    );
    expect(result.current.isRasterOrVrt).toBe(false);
  });

  it('transitions to error after 10s timeout for raster', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );
    expect(result.current.heroState).toBe('loading');

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(result.current.heroState).toBe('error');
  });

  it('does not timeout for non-raster datasets', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'vector_dataset', hasTileUrl: false }),
    );

    act(() => {
      vi.advanceTimersByTime(15_000);
    });

    expect(result.current.heroState).toBe('loading');
  });

  it('transitions to loaded via onMapReady', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );

    act(() => {
      result.current.onMapReady();
    });

    expect(result.current.heroState).toBe('loaded');
  });

  it('transitions to error via onTileError', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );

    act(() => {
      result.current.onTileError();
    });

    expect(result.current.heroState).toBe('error');
  });

  it('handleRetry resets to loading and increments mapKey', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );

    act(() => {
      result.current.onTileError();
    });
    expect(result.current.heroState).toBe('error');
    expect(result.current.retryCount).toBe(0);

    act(() => {
      result.current.handleRetry();
    });

    expect(result.current.heroState).toBe('loading');
    expect(result.current.retryCount).toBe(1);
    expect(result.current.mapKey).toBe(1);
  });

  it('skips to loaded for raster with no tile URL', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: false }),
    );
    expect(result.current.heroState).toBe('loaded');
  });

  it('resets state when datasetId changes', () => {
    const { result, rerender } = renderHook(
      ({ datasetId }) =>
        useHeroState({ datasetId, recordType: 'raster_dataset', hasTileUrl: true }),
      { initialProps: { datasetId: 'd1' } },
    );

    act(() => {
      result.current.onTileError();
    });
    expect(result.current.heroState).toBe('error');
    expect(result.current.retryCount).toBe(0);

    act(() => {
      result.current.handleRetry();
    });
    expect(result.current.retryCount).toBe(1);

    rerender({ datasetId: 'd2' });

    expect(result.current.heroState).toBe('loading');
    expect(result.current.retryCount).toBe(0);
    expect(result.current.mapKey).toBe(0);
  });

  it('skips to loaded when navigating between two raster datasets without tile URLs', () => {
    const { result, rerender } = renderHook(
      ({ datasetId }) =>
        useHeroState({ datasetId, recordType: 'raster_dataset', hasTileUrl: false }),
      { initialProps: { datasetId: 'd1' } },
    );

    expect(result.current.heroState).toBe('loaded');

    // Navigate to second raster dataset, also without tile URL
    rerender({ datasetId: 'd2' });

    // Should skip back to loaded (not stuck at loading)
    expect(result.current.heroState).toBe('loaded');
  });
});
