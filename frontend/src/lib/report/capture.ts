// Global capture installer for the in-app problem reporter.
//
// Patches console.error / console.warn (preserving the original devtools output)
// and adds window 'error' / 'unhandledrejection' listeners — the two signal
// sources that have no existing hook in the codebase. The other sources
// (TanStack Query failures, MapLibre errors, React error boundaries) push into
// the buffer from their own call sites.
//
// Idempotent: safe to call multiple times (StrictMode, Vite HMR re-exec).

import { pushReportEntry } from './report-buffer';

let installed = false;

function formatArgs(args: unknown[]): string {
  return args
    .map((arg) => {
      if (typeof arg === 'string') return arg;
      if (arg instanceof Error) return arg.message;
      try {
        return JSON.stringify(arg);
      } catch {
        return String(arg);
      }
    })
    .join(' ')
    .trim();
}

function firstStack(args: unknown[]): string | undefined {
  const err = args.find((arg): arg is Error => arg instanceof Error);
  return err?.stack;
}

export function initReportCapture(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;

  // Intercept console.error/warn so they feed the report buffer while still
  // printing to devtools as usual.
  const originalError = console.error.bind(console);
  const originalWarn = console.warn.bind(console);

  console.error = (...args: unknown[]) => {
    originalError(...args);
    pushReportEntry({
      severity: 'error',
      source: 'console',
      message: formatArgs(args) || 'console.error',
      detail: firstStack(args),
    });
  };

  console.warn = (...args: unknown[]) => {
    originalWarn(...args);
    pushReportEntry({
      severity: 'warning',
      source: 'console',
      message: formatArgs(args) || 'console.warn',
    });
  };

  window.addEventListener('error', (event: ErrorEvent) => {
    pushReportEntry({
      severity: 'error',
      source: 'runtime',
      message: event.message || event.error?.message || 'Uncaught error',
      detail: event.error?.stack,
    });
  });

  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    pushReportEntry({
      severity: 'error',
      source: 'runtime',
      message: reason instanceof Error ? reason.message : `Unhandled rejection: ${String(reason)}`,
      detail: reason instanceof Error ? reason.stack : undefined,
    });
  });
}
