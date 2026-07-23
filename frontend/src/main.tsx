import React from 'react';
import ReactDOM, { type Root } from 'react-dom/client';
import { createBrowserRouter, createRoutesFromElements, RouterProvider } from 'react-router';
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { ThemeProvider } from '@/components/theme-provider';
import { useTheme } from '@/components/theme-provider';
import { TooltipProvider } from '@/components/ui/tooltip';
import { initializeI18n } from '@/i18n';
import { AppErrorBoundary } from '@/components/error';
import { ApiError } from '@/api/client';
import { initReportCapture, pushReportEntry, redact, reportNetworkError } from '@/lib/report';
import { installStaleAssetReload } from '@/lib/stale-asset-reload';
import { wireAuthCacheReset } from '@/lib/auth-cache-reset';
import { ReportProblemHost } from '@/components/report/ReportProblemHost';
import { appRoutes } from './App';
import './index.css';

// Start capturing console/network/error signal at app load so the in-app
// problem reporter has history ready the moment a user opens it.
initReportCapture();

// fix(#645): self-heal tabs whose lazy route chunks vanished behind a deploy.
installStaleAssetReload();

function reportQueryKey(key: unknown): string | undefined {
  // Surface only the query's namespace (the first string segment, e.g.
  // 'shared-map'). Later segments are parameters — ids, share tokens, api keys —
  // that can carry secrets and aren't reliably distinguishable from safe ids by
  // shape, so they're dropped rather than serialized into the report. redact()
  // is a belt-and-suspenders pass in case a namespace ever becomes dynamic.
  if (Array.isArray(key)) {
    const namespace = key.find((part) => typeof part === 'string');
    return typeof namespace === 'string' ? redact(namespace) : undefined;
  }
  if (typeof key === 'string') return redact(key);
  return undefined;
}

function captureQueryError(error: unknown, key: unknown): void {
  if (error instanceof ApiError) {
    // Skip the expected 401 the client throws while a session is being
    // refreshed/expired — it would just be noise in a bug report.
    if (error.status === 401) return;
    reportNetworkError({ status: error.status, url: reportQueryKey(key), detail: error.body ?? error.message });
  } else if (error instanceof Error) {
    pushReportEntry({ severity: 'error', source: 'runtime', message: error.message, detail: error.stack });
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
  queryCache: new QueryCache({
    onError: (error, query) => captureQueryError(error, query.queryKey),
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => captureQueryError(error, mutation.options.mutationKey),
  }),
});

// fix(#430 codex r6): evict every cached query when the signed-in identity
// changes so one user's cached rows never render for the next (see module doc).
wireAuthCacheReset(queryClient);

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  // #305: richColors differentiates success/error/warning/info by
  // hue (was a single neutral surface for all 183 call sites); closeButton
  // makes every toast dismissable.
  return <Toaster theme={resolvedTheme} richColors closeButton />;
}

const router = createBrowserRouter(createRoutesFromElements(appRoutes));

// Cache the React root on the container so a Vite HMR re-exec of this entry
// module reuses it instead of calling createRoot() twice on the same node
// (MAPS-01 / #122). Type-only; erased at runtime.
interface RootContainer extends HTMLElement { __glRoot?: Root }

// fix(#438): PERF-01 — awaiting initializeI18n() before the first render blocks
// non-English first paint on the locale chunk (en is bundled, so it is
// unaffected). This is a deliberate no-FOUC trade-off: rendering before the
// bundle resolves would flash raw keys. Upgrade path: render en immediately and
// background-swap the locale, or ship a static skeleton in index.html.
async function bootstrap() {
  await initializeI18n();

  const container = document.getElementById('root')! as RootContainer;
  const root = container.__glRoot ?? ReactDOM.createRoot(container);
  container.__glRoot = root;
  root.render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider defaultTheme="system" storageKey="geolens-theme">
          <TooltipProvider>
            <AppErrorBoundary>
              <RouterProvider router={router} />
            </AppErrorBoundary>
            {/* Mounted OUTSIDE AppErrorBoundary (but inside the shared
                providers) so the problem reporter and its toasts survive an
                app-level crash: componentDidCatch records the crash in the
                buffer, and the floating button overlays the error fallback so
                the user can still open a pre-filled report. */}
            <ThemedToaster />
            <ReportProblemHost />
          </TooltipProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

void bootstrap();
