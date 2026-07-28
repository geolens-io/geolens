import { renderHook } from '@testing-library/react';
import { useTileAuthRecovery } from '@/hooks/use-tile-auth-recovery';

// fix(#621): one re-mint per cooldown window — MapLibre can fire dozens of
// tile errors per pan, and hammering the mint endpoint cannot help. Errors in
// the settle window ride the pending re-mint (true); errors that persist past
// it mean the re-mint didn't cure them (false).

describe('useTileAuthRecovery', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('kicks the re-mint on the first error and reports it handled', () => {
    const remint = vi.fn();
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('suppresses error UI for the rest of the burst while the re-mint settles', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 500);
    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 9_000);
    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('reports failure when errors persist after the settle window', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 15_000);
    expect(result.current()).toBe(false);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('allows another re-mint once the cooldown has elapsed', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 31_000);
    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(2);
  });
});
