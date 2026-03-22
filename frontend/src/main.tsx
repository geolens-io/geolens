import React from 'react';
import ReactDOM from 'react-dom/client';
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
    queries: { staleTime: 30_000, retry: 1 },
  },
});

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} />;
}

const router = createBrowserRouter(createRoutesFromElements(appRoutes));

async function bootstrap() {
  await initializeI18n();

  ReactDOM.createRoot(document.getElementById('root')!).render(
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
