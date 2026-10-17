import { useEffect, useState } from 'react';

// setTimeout stores its delay as a signed 32-bit integer and fires at once beyond it.
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

/**
 * Current time that advances when the soonest future expiry passes, so a list
 * left open re-renders a key as expired. Sets no timer when nothing is pending.
 */
export function useExpiryClock(expiries: ReadonlyArray<string | null | undefined>): Date {
  const [now, setNow] = useState(() => new Date());

  let nextAt: number | null = null;
  for (const expiry of expiries) {
    if (!expiry) continue;
    const at = new Date(expiry).getTime();
    if (at > now.getTime() && (nextAt === null || at < nextAt)) nextAt = at;
  }

  useEffect(() => {
    if (nextAt === null) return;
    // The extra millisecond keeps the wake-up past the expiry instant.
    const delay = Math.min(Math.max(nextAt - Date.now(), 0) + 1, MAX_TIMEOUT_MS);
    const id = setTimeout(() => setNow(new Date()), delay);
    return () => clearTimeout(id);
  }, [nextAt, now]);

  return now;
}
