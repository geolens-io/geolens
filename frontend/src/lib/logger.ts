// DEV-guarded console wrappers so production builds don't surface noisy
// `[ComponentName] error: ...` lines in user devtools. For sites that should only
// surface in development; inline `if (import.meta.env.DEV)` guards are equivalent.

const isDev = import.meta.env.DEV;

export const logger = {
  error: (...args: unknown[]) => {
    if (isDev) console.error(...args);
  },
  warn: (...args: unknown[]) => {
    if (isDev) console.warn(...args);
  },
};
