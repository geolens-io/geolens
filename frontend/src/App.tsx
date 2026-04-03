import { lazy, Suspense } from 'react';
import { Route, Navigate, Outlet } from 'react-router';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { AdminRoute } from '@/components/auth/AdminRoute';
import { EditorRoute } from '@/components/auth/EditorRoute';
import { AppLayout } from '@/components/layout/AppLayout';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { LoadingState } from '@/components/layout/LoadingState';
import { LazyLoadErrorBoundary, RouteErrorBoundary } from '@/components/error';

// Lazy page imports — each produces a separate Vite chunk
const LoginPage = lazy(() => import('./pages/LoginPage').then(m => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import('./pages/RegisterPage').then(m => ({ default: m.RegisterPage })));
const OAuthCallbackPage = lazy(() => import('./pages/OAuthCallbackPage').then(m => ({ default: m.OAuthCallbackPage })));
const PublicViewerPage = lazy(() => import('./pages/PublicViewerPage').then(m => ({ default: m.PublicViewerPage })));
const SearchPage = lazy(() => import('./pages/SearchPage').then(m => ({ default: m.SearchPage })));
const DatasetPage = lazy(() => import('./pages/DatasetPage').then(m => ({ default: m.DatasetPage })));
const CollectionsPage = lazy(() => import('./pages/CollectionsPage').then(m => ({ default: m.CollectionsPage })));
const CollectionDetailPage = lazy(() => import('./pages/CollectionDetailPage').then(m => ({ default: m.CollectionDetailPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const ImportPage = lazy(() => import('./pages/ImportPage').then(m => ({ default: m.ImportPage })));
const MapsPage = lazy(() => import('./pages/MapsPage').then(m => ({ default: m.MapsPage })));
const MapViewerGate = lazy(() => import('./pages/MapViewerGate').then(m => ({ default: m.MapViewerGate })));
const AdminOverviewPage = lazy(() => import('./pages/admin/AdminOverviewPage').then(m => ({ default: m.AdminOverviewPage })));
const AdminUsersPage = lazy(() => import('./pages/admin/AdminUsersPage').then(m => ({ default: m.AdminUsersPage })));
const AdminJobsPage = lazy(() => import('./pages/admin/AdminJobsPage').then(m => ({ default: m.AdminJobsPage })));
const AdminAuditPage = lazy(() => import('./pages/admin/AdminAuditPage').then(m => ({ default: m.AdminAuditPage })));
const AdminSharedMapsPage = lazy(() => import('./pages/admin/AdminSharedMapsPage').then(m => ({ default: m.AdminSharedMapsPage })));

// Settings (per-tab routes)
const AdminSettingsPage = lazy(() => import('./pages/admin/AdminSettingsPage').then(m => ({ default: m.AdminSettingsPage })));
const AdminConfigOpsPage = lazy(() => import('./pages/admin/AdminConfigOpsPage').then(m => ({ default: m.AdminConfigOpsPage })));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage })));

function RootLayout() {
  return (
    <LazyLoadErrorBoundary>
      <Suspense fallback={<LoadingState />}>
        <Outlet />
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}

export const appRoutes = (
  <Route element={<RootLayout />}>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
    <Route path="/m/:token" element={<PublicViewerPage />} />
    <Route element={<AppLayout />} errorElement={<RouteErrorBoundary />}>
      {/* Public routes — no auth required */}
      <Route index element={<SearchPage />} />
      <Route path="datasets/:id" element={<DatasetPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="collections" element={<CollectionsPage />} />
      <Route path="collections/:id" element={<CollectionDetailPage />} />
      <Route path="maps" element={<MapsPage />} />
      <Route path="maps/:id" element={<MapViewerGate />} errorElement={<RouteErrorBoundary />} />

      {/* Protected routes — auth required */}
      <Route element={<ProtectedRoute />}>
        <Route path="settings" element={<SettingsPage />} />
        <Route element={<EditorRoute />} errorElement={<RouteErrorBoundary />}>
          <Route path="import" element={<ImportPage />} />
        </Route>
        <Route element={<AdminRoute />} errorElement={<RouteErrorBoundary />}>
          <Route element={<AdminLayout />}>
            <Route path="admin" element={<Navigate to="/admin/overview" replace />} />
            <Route path="admin/overview" element={<AdminOverviewPage />} />
            <Route path="admin/users" element={<AdminUsersPage />} />
            <Route path="admin/jobs" element={<AdminJobsPage />} />
            <Route path="admin/audit" element={<AdminAuditPage />} />
            <Route path="admin/shared-maps" element={<AdminSharedMapsPage />} />
            {/* Redirects from old routes */}
            <Route path="admin/share-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
            <Route path="admin/embed-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
            {/* Settings — each tab is its own route */}
            <Route path="admin/settings" element={<Navigate to="/admin/settings/general" replace />} />
            <Route path="admin/settings/:tab" element={<AdminSettingsPage />} />
            <Route path="admin/config-ops" element={<AdminConfigOpsPage />} />
            {/* Redirects from old routes */}
            <Route path="admin/settings/infrastructure" element={<Navigate to="/admin/overview" replace />} />
            <Route path="admin/general" element={<Navigate to="/admin/settings/general" replace />} />
            <Route path="admin/basemaps" element={<Navigate to="/admin/settings/map" replace />} />
            <Route path="admin/map-defaults" element={<Navigate to="/admin/settings/map" replace />} />
            <Route path="admin/settings/appearance" element={<Navigate to="/admin/settings/map" replace />} />
            <Route path="admin/security" element={<Navigate to="/admin/settings/auth" replace />} />
            <Route path="admin/uploads" element={<Navigate to="/admin/settings/storage" replace />} />
            <Route path="admin/ai" element={<Navigate to="/admin/settings/ai" replace />} />
            <Route path="admin/infrastructure" element={<Navigate to="/admin/overview" replace />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Route>
  </Route>
);
