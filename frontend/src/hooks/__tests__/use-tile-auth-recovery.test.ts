import { renderHook } from '@testing-library/react';
import { useTileAuthRecovery } from '@/hooks/use-tile-auth-recovery';

// fix(#621): one re-mint per cooldown window — MapLibre can fire dozens of
// tile errors per pan, and hammering the mint endpoint cannot help.

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

  it('suppresses further re-mints inside the cooldown window', () => {
    const remint = vi.fn();
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    expect(result.current()).toBe(false);
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
