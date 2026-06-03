// Phase 276 CODE-11: DEV-guarded console wrappers so production builds
// don't surface the noisy `[ComponentName] error: ...` lines in user
// devtools. Server-side log shipping (Sentry, Datadog, etc.) is
// out of scope — add a sink hook here if/when we wire that up.
//
// Use this at sites that should ONLY surface in development. The codebase
// also uses inline `if (import.meta.env.DEV) console.warn(...)` guards;
// either pattern is acceptable, but new code should prefer this helper.

const isDev = import.meta.env.DEV;

export const logger = {
  error: (...args: unknown[]) => {
    if (isDev) console.error(...args);
  },
  warn: (...args: unknown[]) => {
    if (isDev) console.warn(...args);
  },
  // info / debug intentionally omitted — add when there's a real consumer
};
