import { signalWithTimeout } from './abort';

describe('signalWithTimeout', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('follows the caller signal', () => {
    const c = new AbortController();
    const s = signalWithTimeout(c.signal, 60_000);
    c.abort(new Error('stale'));
    expect(s.aborted).toBe(true);
  });

  it('falls back to manual composition when AbortSignal.any is missing', () => {
    const original = AbortSignal.any;
    // @ts-expect-error simulating an older browser
    AbortSignal.any = undefined;
    try {
      const c = new AbortController();
      const s = signalWithTimeout(c.signal, 60_000);
      expect(s.aborted).toBe(false);
      c.abort(new Error('stale'));
      expect(s.aborted).toBe(true);
    } finally {
      AbortSignal.any = original;
    }
  });
});
