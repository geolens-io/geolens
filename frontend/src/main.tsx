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
import { initReportCapture, pushReportEntry, reportNetworkError } from '@/lib/report';
import { ReportProblemHost } from '@/components/report/ReportProblemHost';
import { appRoutes } from './App';
import './index.css';

// Start capturing console/network/error signal at app load so the in-app
// problem reporter has history ready the moment a user opens it.
initReportCapture();

function reportQueryKey(key: unknown): string | undefined {
  if (Array.isArray(key)) return key.map((part) => String(part)).join('/');
  if (key == null) return undefined;
  return String(key);
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

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} />;
}

const router = createBrowserRouter(createRoutesFromElements(appRoutes));

// Cache the React root on the container so a Vite HMR re-exec of this entry
// module reuses it instead of calling createRoot() twice on the same node
// (MAPS-01 / #122). Type-only; erased at runtime.
interface RootContainer extends HTMLElement { __glRoot?: Root }

async function bootstrap() {
  await initializeI18n();

  const container = document.getElementById('root')! as RootContainer;
  const root = container.__glRoot ?? ReactDOM.createRoot(container);
  container.__glRoot = root;
  root.render(
    <React.StrictMode>
      <AppErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider defaultTheme="system" storageKey="geolens-theme">
            <TooltipProvider>
              <RouterProvider router={router} />
              <ThemedToaster />
              <ReportProblemHost />
            </TooltipProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </AppErrorBoundary>
    </React.StrictMode>,
  );
}

void bootstrap();
