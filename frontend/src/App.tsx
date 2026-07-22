import { lazy, Suspense } from 'react';
import { Route, Navigate, Outlet } from 'react-router';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { AdminCapabilityRoute, AdminIndexRoute, AdminRoute } from '@/components/auth/AdminRoute';
import { LandingFirstGuard } from '@/components/auth/LandingFirstGuard';
import { EditorRoute } from '@/components/auth/EditorRoute';
import { AppLayout } from '@/components/layout/AppLayout';
import { SiteBanner } from '@/components/layout/SiteBanner';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { LoadingState } from '@/components/layout/LoadingState';
import { LazyLoadErrorBoundary, RouteErrorBoundary } from '@/components/error';
import { SessionExpiredDialog } from '@/components/auth/SessionExpiredDialog';

// Lazy page imports — each produces a separate Vite chunk
const LoginPage = lazy(() => import('./pages/LoginPage').then(m => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import('./pages/RegisterPage').then(m => ({ default: m.RegisterPage })));
const VerifyEmailPage = lazy(() => import('./pages/VerifyEmailPage').then(m => ({ default: m.VerifyEmailPage })));
const OAuthCallbackPage = lazy(() => import('./pages/OAuthCallbackPage').then(m => ({ default: m.OAuthCallbackPage })));
// fix(#448): map routes kick off the map-vendor chunk (~306KB gz, maplibre-gl)
// in parallel with the route chunk. Without this the vendor download
// serializes BEHIND the page chunk — the page module only reaches its own
// maplibre import after it has itself loaded.
const PublicViewerPage = lazy(() =>
  Promise.all([import('./pages/PublicViewerPage'), import('maplibre-gl')]).then(
    ([m]) => ({ default: m.PublicViewerPage }),
  ),
);
const DatasetPage = lazy(() => import('./pages/DatasetPage').then(m => ({ default: m.DatasetPage })));
const CollectionsPage = lazy(() => import('./pages/CollectionsPage').then(m => ({ default: m.CollectionsPage })));
const CollectionDetailPage = lazy(() => import('./pages/CollectionDetailPage').then(m => ({ default: m.CollectionDetailPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const ImportPage = lazy(() => import('./pages/ImportPage').then(m => ({ default: m.ImportPage })));
const MapsPage = lazy(() => import('./pages/MapsPage').then(m => ({ default: m.MapsPage })));
// fix(#448): see PublicViewerPage — warm map-vendor alongside the route chunk.
const MapViewerGate = lazy(() =>
  Promise.all([import('./pages/MapViewerGate'), import('maplibre-gl')]).then(
    ([m]) => ({ default: m.MapViewerGate }),
  ),
);
const AdminOverviewPage = lazy(() => import('./pages/admin/AdminOverviewPage').then(m => ({ default: m.AdminOverviewPage })));
const AdminUsersPage = lazy(() => import('./pages/admin/AdminUsersPage').then(m => ({ default: m.AdminUsersPage })));
const AdminJobsPage = lazy(() => import('./pages/admin/AdminJobsPage').then(m => ({ default: m.AdminJobsPage })));
const AdminAuditPage = lazy(() => import('./pages/admin/AdminAuditPage').then(m => ({ default: m.AdminAuditPage })));
const AdminSharedMapsPage = lazy(() => import('./pages/admin/AdminSharedMapsPage').then(m => ({ default: m.AdminSharedMapsPage })));
const AdminSamlPage = lazy(() => import('./pages/admin/AdminSamlPage').then(m => ({ default: m.AdminSamlPage })));

// Settings (per-tab routes)
const AdminSettingsPage = lazy(() => import('./pages/admin/AdminSettingsPage').then(m => ({ default: m.AdminSettingsPage })));
const AdminConfigOpsPage = lazy(() => import('./pages/admin/AdminConfigOpsPage').then(m => ({ default: m.AdminConfigOpsPage })));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage })));

function RootLayout() {
  return (
    <LazyLoadErrorBoundary>
      {/* fix(#628): global session-expiry host — needs router context for the
          sign-in-returns-to-route action, so it lives here rather than main.tsx. */}
      <SessionExpiredDialog />
      <Suspense fallback={<LoadingState />}>
        <Outlet />
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}

// fix(#553): auth pages live outside AppLayout but should still show the
// admin-configured announcement banner. Their min-h-screen shells tolerate
// the extra banner height; full-height shells (AppLayout map routes,
// PublicViewerPage) mount SiteBanner inside their own flex column instead.
function BannerShell() {
  return (
    <>
      <SiteBanner />
      <Outlet />
    </>
  );
}

export const appRoutes = (
  <Route element={<RootLayout />}>
    <Route element={<BannerShell />}>
      <Route path="/login" element={<LoginPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="/register" element={<RegisterPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="/oauth/callback" element={<OAuthCallbackPage />} errorElement={<RouteErrorBoundary />} />
    </Route>
    <Route path="/m/:token" element={<PublicViewerPage />} errorElement={<RouteErrorBoundary />} />
    <Route element={<AppLayout />} errorElement={<RouteErrorBoundary />}>
      {/* Public routes — no auth required */}
      {/* FRONT-01: LandingFirstGuard redirects anonymous visitors to /login
          when the landing_first flag is ON; otherwise renders SearchPage. */}
      <Route index element={<LandingFirstGuard />} errorElement={<RouteErrorBoundary />} />
      <Route path="search" element={<Navigate to="/" replace />} />
      <Route path="datasets/:id" element={<DatasetPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="collections" element={<CollectionsPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="collections/:id" element={<CollectionDetailPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="maps" element={<MapsPage />} errorElement={<RouteErrorBoundary />} />
      <Route path="maps/new" element={<Navigate to="/maps" replace />} />
      <Route path="maps/:id" element={<MapViewerGate />} errorElement={<RouteErrorBoundary />} />

      {/* Protected routes — auth required */}
      <Route element={<ProtectedRoute />} errorElement={<RouteErrorBoundary />}>
        <Route path="settings" element={<SettingsPage />} errorElement={<RouteErrorBoundary />} />
        <Route element={<EditorRoute />} errorElement={<RouteErrorBoundary />}>
          <Route path="import" element={<ImportPage />} errorElement={<RouteErrorBoundary />} />
        </Route>
          <Route element={<AdminRoute />} errorElement={<RouteErrorBoundary />}>
            <Route element={<AdminLayout />} errorElement={<RouteErrorBoundary />}>
            <Route path="admin" element={<AdminIndexRoute />} />
            <Route element={<AdminCapabilityRoute capability="manage_users" />}>
              <Route path="admin/overview" element={<AdminOverviewPage />} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/users" element={<AdminUsersPage />} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/jobs" element={<AdminJobsPage />} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/shared-maps" element={<AdminSharedMapsPage />} errorElement={<RouteErrorBoundary />} />
            </Route>
            <Route element={<AdminCapabilityRoute capability="manage_settings" />}>
              <Route path="admin/audit" element={<AdminAuditPage />} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/saml" element={<AdminSamlPage />} errorElement={<RouteErrorBoundary />} />
              {/* Settings — each tab is its own route */}
              <Route path="admin/settings" element={<Navigate to="/admin/settings/general" replace />} />
              <Route path="admin/settings/:tab" element={<AdminSettingsPage />} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/config-ops" element={<AdminConfigOpsPage />} errorElement={<RouteErrorBoundary />} />
            </Route>
            {/* Redirects from old routes */}
            <Route path="admin/share-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
            <Route path="admin/embed-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
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
