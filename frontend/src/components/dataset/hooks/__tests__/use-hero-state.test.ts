import { renderHook, act } from '@testing-library/react';
import { useHeroState } from '@/components/dataset/hooks/use-hero-state';

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

  it('does not timeout for table datasets', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'table', hasTileUrl: false }),
    );

    act(() => {
      vi.advanceTimersByTime(15_000);
    });

    expect(result.current.heroState).toBe('loading');
  });

  it('times out for vector datasets that never report ready', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'vector_dataset', hasTileUrl: false }),
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(result.current.heroState).toBe('error');
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

  // #1362 codex r4: a completed replacement is not a failed-tile retry —
  // routing it through handleRetry would spend the 3-attempt manual-retry
  // budget on a SUCCESS, leaving a later genuine tile failure unretryable.
  it('handleReplaceComplete resets to loading, bumps mapKey, and does NOT spend the retry budget', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );

    act(() => {
      result.current.handleReplaceComplete();
    });

    expect(result.current.heroState).toBe('loading');
    expect(result.current.mapKey).toBe(1);
    expect(result.current.retryCount).toBe(0);
  });

  it('handleReplaceComplete resets an already-spent retry budget instead of adding to it', () => {
    const { result } = renderHook(() =>
      useHeroState({ datasetId: 'd1', recordType: 'raster_dataset', hasTileUrl: true }),
    );

    // Exhaust the manual-retry budget first.
    act(() => { result.current.onTileError(); });
    act(() => { result.current.handleRetry(); });
    act(() => { result.current.onTileError(); });
    act(() => { result.current.handleRetry(); });
    act(() => { result.current.onTileError(); });
    act(() => { result.current.handleRetry(); });
    expect(result.current.retryCount).toBe(3);

    act(() => {
      result.current.handleReplaceComplete();
    });

    // A successful replace hands back a fresh budget rather than pushing
    // retryCount even further past the Retry-button cutoff.
    expect(result.current.retryCount).toBe(0);
    expect(result.current.heroState).toBe('loading');
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
