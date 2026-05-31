import React from 'react';
import ReactDOM, { type Root } from 'react-dom/client';
import { createBrowserRouter, createRoutesFromElements, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { ThemeProvider } from '@/components/theme-provider';
import { useTheme } from '@/components/theme-provider';
import { TooltipProvider } from '@/components/ui/tooltip';
import { initializeI18n } from '@/i18n';
import { AppErrorBoundary } from '@/components/error';
import { appRoutes } from './App';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
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
            </TooltipProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </AppErrorBoundary>
    </React.StrictMode>,
  );
}

void bootstrap();
