import { lazy, Suspense } from 'react';
import { Route, Navigate, Outlet, useLocation } from 'react-router';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { AdminCapabilityRoute, AdminIndexRoute, AdminRoute, AdminSettingsRoute } from '@/components/auth/AdminRoute';
import { LandingFirstGuard } from '@/components/auth/LandingFirstGuard';
import { EditorRoute } from '@/components/auth/EditorRoute';
import { AppLayout } from '@/components/layout/AppLayout';
import { SiteBanner } from '@/components/layout/SiteBanner';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { LoadingState } from '@/components/layout/LoadingState';
import { LazyLoadErrorBoundary, RouteErrorBoundary } from '@/components/error';
import { SessionExpiredDialog } from '@/components/auth/SessionExpiredDialog';
import { SessionRestoreNotice } from '@/components/auth/SessionRestoreNotice';
import { AnalysisJobWatcher } from '@/components/analysis/AnalysisJobWatcher';
import { preload, requires } from '@/lib/route-preload';

const loadLoginPage = () =>
  import('./pages/LoginPage').then(m => ({ default: m.LoginPage }));
const LoginPage = lazy(loadLoginPage);
const loadRegisterPage = () =>
  import('./pages/RegisterPage').then(m => ({ default: m.RegisterPage }));
const RegisterPage = lazy(loadRegisterPage);
const loadVerifyEmailPage = () =>
  import('./pages/VerifyEmailPage').then(m => ({ default: m.VerifyEmailPage }));
const VerifyEmailPage = lazy(loadVerifyEmailPage);
const loadTrustBrowserPage = () =>
  import('./pages/TrustBrowserPage').then(m => ({ default: m.TrustBrowserPage }));
const TrustBrowserPage = lazy(loadTrustBrowserPage);
const loadOAuthCallbackPage = () =>
  import('./pages/OAuthCallbackPage').then(m => ({ default: m.OAuthCallbackPage }));
const OAuthCallbackPage = lazy(loadOAuthCallbackPage);
// Map routes load the maplibre-gl vendor chunk in parallel with the route
// chunk; otherwise it downloads only after the page module has loaded.
const loadPublicViewerPage = () =>
  Promise.all([import('./pages/PublicViewerPage'), import('maplibre-gl')]).then(
    ([m]) => ({ default: m.PublicViewerPage }),
  );
const PublicViewerPage = lazy(loadPublicViewerPage);
const loadDatasetPage = () =>
  import('./pages/DatasetPage').then(m => ({ default: m.DatasetPage }));
const DatasetPage = lazy(loadDatasetPage);
const loadCollectionsPage = () =>
  import('./pages/CollectionsPage').then(m => ({ default: m.CollectionsPage }));
const CollectionsPage = lazy(loadCollectionsPage);
const loadCollectionDetailPage = () =>
  import('./pages/CollectionDetailPage').then(m => ({ default: m.CollectionDetailPage }));
const CollectionDetailPage = lazy(loadCollectionDetailPage);
const loadSettingsPage = () =>
  import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage }));
const SettingsPage = lazy(loadSettingsPage);
const loadImportPage = () =>
  import('./pages/ImportPage').then(m => ({ default: m.ImportPage }));
const ImportPage = lazy(loadImportPage);
const loadMapsPage = () =>
  import('./pages/MapsPage').then(m => ({ default: m.MapsPage }));
const MapsPage = lazy(loadMapsPage);
const loadMapViewerGate = () =>
  Promise.all([import('./pages/MapViewerGate'), import('maplibre-gl')]).then(
    ([m]) => ({ default: m.MapViewerGate }),
  );
const MapViewerGate = lazy(loadMapViewerGate);
const loadAdminOverviewPage = () =>
  import('./pages/admin/AdminOverviewPage').then(m => ({ default: m.AdminOverviewPage }));
const AdminOverviewPage = lazy(loadAdminOverviewPage);
const loadAdminUsersPage = () =>
  import('./pages/admin/AdminUsersPage').then(m => ({ default: m.AdminUsersPage }));
const AdminUsersPage = lazy(loadAdminUsersPage);
const loadAdminGroupsPage = () =>
  import('./pages/admin/AdminGroupsPage').then(m => ({ default: m.AdminGroupsPage }));
const AdminGroupsPage = lazy(loadAdminGroupsPage);
const loadAdminJobsPage = () =>
  import('./pages/admin/AdminJobsPage').then(m => ({ default: m.AdminJobsPage }));
const AdminJobsPage = lazy(loadAdminJobsPage);
const loadAdminAuditPage = () =>
  import('./pages/admin/AdminAuditPage').then(m => ({ default: m.AdminAuditPage }));
const AdminAuditPage = lazy(loadAdminAuditPage);
const loadAdminSharedMapsPage = () =>
  import('./pages/admin/AdminSharedMapsPage').then(m => ({ default: m.AdminSharedMapsPage }));
const AdminSharedMapsPage = lazy(loadAdminSharedMapsPage);
const loadAdminSamlPage = () =>
  import('./pages/admin/AdminSamlPage').then(m => ({ default: m.AdminSamlPage }));
const AdminSamlPage = lazy(loadAdminSamlPage);

const loadAdminSettingsPage = () =>
  import('./pages/admin/AdminSettingsPage').then(m => ({ default: m.AdminSettingsPage }));
const AdminSettingsPage = lazy(loadAdminSettingsPage);
const loadAdminConfigOpsPage = () =>
  import('./pages/admin/AdminConfigOpsPage').then(m => ({ default: m.AdminConfigOpsPage }));
const AdminConfigOpsPage = lazy(loadAdminConfigOpsPage);
const loadNotFoundPage = () =>
  import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage }));
const NotFoundPage = lazy(loadNotFoundPage);

function RootLayout() {
  return (
    <LazyLoadErrorBoundary>
      {/* Needs router context for the sign-in-returns-to-route action, so it
          lives here rather than main.tsx. */}
      <SessionExpiredDialog />
      <SessionRestoreNotice />
      {/* Analysis-job notifier, global so a materialize job that outlives the
          builder still reports when it lands. Needs router context for its
          "View dataset" action. A job still RUNNING at reload survives it
          (the persisted store carries it); the completion toast is
          `duration: Infinity` and NOT persisted, so a reload while it sits
          unacknowledged drops the notification. The dataset is already in the
          catalog, so that is accepted. */}
      <AnalysisJobWatcher />
      <Suspense fallback={<LoadingState />}>
        <Outlet />
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}

// Auth pages live outside AppLayout but still show the announcement banner.
// Their min-h-screen shells tolerate the extra height; full-height shells
// (AppLayout map routes, PublicViewerPage) mount SiteBanner in their own flex
// column instead.
function BannerShell() {
  return (
    <>
      <SiteBanner />
      <Outlet />
    </>
  );
}

// Search lives on the home page; keep the query so old /search?q= links still work.
function SearchRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: '/', search, hash }} replace />;
}

export const appRoutes = (
  <Route element={<RootLayout />}>
    <Route element={<BannerShell />}>
      <Route path="/login" element={<LoginPage />} handle={preload(loadLoginPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="/login/trust" element={<TrustBrowserPage />} handle={preload(loadTrustBrowserPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="/register" element={<RegisterPage />} handle={preload(loadRegisterPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} handle={preload(loadVerifyEmailPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="/oauth/callback" element={<OAuthCallbackPage />} handle={preload(loadOAuthCallbackPage)} errorElement={<RouteErrorBoundary />} />
    </Route>
    <Route path="/m/:token" element={<PublicViewerPage />} handle={preload(loadPublicViewerPage)} errorElement={<RouteErrorBoundary />} />
    <Route element={<AppLayout />} errorElement={<RouteErrorBoundary />}>
      {/* Public routes — no auth required */}
      {/* LandingFirstGuard redirects anonymous visitors to /login when the
          landing_first flag is ON; otherwise renders SearchPage. */}
      <Route index element={<LandingFirstGuard />} errorElement={<RouteErrorBoundary />} />
      <Route path="search" element={<SearchRedirect />} />
      <Route path="datasets/:id" element={<DatasetPage />} handle={preload(loadDatasetPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="collections" element={<CollectionsPage />} handle={preload(loadCollectionsPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="collections/:id" element={<CollectionDetailPage />} handle={preload(loadCollectionDetailPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="maps" element={<MapsPage />} handle={preload(loadMapsPage)} errorElement={<RouteErrorBoundary />} />
      <Route path="maps/new" element={<Navigate to="/maps" replace />} />
      <Route path="maps/:id" element={<MapViewerGate />} handle={preload(loadMapViewerGate)} errorElement={<RouteErrorBoundary />} />

      {/* Protected routes — auth required */}
      <Route element={<ProtectedRoute />} handle={requires('user')} errorElement={<RouteErrorBoundary />}>
        <Route path="settings" element={<SettingsPage />} handle={preload(loadSettingsPage)} errorElement={<RouteErrorBoundary />} />
        <Route element={<EditorRoute />} handle={requires('editor')} errorElement={<RouteErrorBoundary />}>
          <Route path="import" element={<ImportPage />} handle={preload(loadImportPage)} errorElement={<RouteErrorBoundary />} />
        </Route>
          <Route element={<AdminRoute />} handle={requires('admin')} errorElement={<RouteErrorBoundary />}>
            <Route element={<AdminLayout />} errorElement={<RouteErrorBoundary />}>
            <Route path="admin" element={<AdminIndexRoute />} />
            <Route element={<AdminCapabilityRoute capability="manage_users" />} handle={requires('capability')}>
              <Route path="admin/overview" element={<AdminOverviewPage />} handle={preload(loadAdminOverviewPage)} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/users" element={<AdminUsersPage />} handle={preload(loadAdminUsersPage)} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/groups" element={<AdminGroupsPage />} handle={preload(loadAdminGroupsPage)} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/jobs" element={<AdminJobsPage />} handle={preload(loadAdminJobsPage)} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/shared-maps" element={<AdminSharedMapsPage />} handle={preload(loadAdminSharedMapsPage)} errorElement={<RouteErrorBoundary />} />
            </Route>
            <Route element={<AdminCapabilityRoute capability="manage_settings" />} handle={requires('capability')}>
              <Route path="admin/audit" element={<AdminAuditPage />} handle={preload(loadAdminAuditPage)} errorElement={<RouteErrorBoundary />} />
            </Route>
            {/* The settings and config-ops APIs flip to manage_tenants in
                multi-tenant mode, so these routes gate mode-aware; plain
                manage_settings would admit per-tenant admins whose settings
                requests all 403. */}
            <Route element={<AdminSettingsRoute />} handle={requires('capability')}>
              {/* Settings — each tab is its own route */}
              <Route path="admin/settings" element={<Navigate to="/admin/settings/general" replace />} />
              <Route path="admin/settings/:tab" element={<AdminSettingsPage />} handle={preload(loadAdminSettingsPage)} errorElement={<RouteErrorBoundary />} />
              <Route path="admin/config-ops" element={<AdminConfigOpsPage />} handle={preload(loadAdminConfigOpsPage)} errorElement={<RouteErrorBoundary />} />
              {/* SAML uses the same mode-aware API as the tabs above. */}
              <Route path="admin/saml" element={<AdminSamlPage />} handle={preload(loadAdminSamlPage)} errorElement={<RouteErrorBoundary />} />
            </Route>
            {/* Redirects from old routes. No `admin/settings/appearance` entry:
                a static path outranks `admin/settings/:tab` and would make the
                enterprise branding tab unreachable. AdminSettingsPage's
                edition gate owns that URL. */}
            <Route path="admin/share-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
            <Route path="admin/embed-tokens" element={<Navigate to="/admin/shared-maps" replace />} />
            <Route path="admin/settings/infrastructure" element={<Navigate to="/admin/overview" replace />} />
            <Route path="admin/general" element={<Navigate to="/admin/settings/general" replace />} />
            <Route path="admin/basemaps" element={<Navigate to="/admin/settings/map" replace />} />
            <Route path="admin/map-defaults" element={<Navigate to="/admin/settings/map" replace />} />
            <Route path="admin/security" element={<Navigate to="/admin/settings/auth" replace />} />
            <Route path="admin/uploads" element={<Navigate to="/admin/settings/storage" replace />} />
            <Route path="admin/ai" element={<Navigate to="/admin/settings/ai" replace />} />
            <Route path="admin/infrastructure" element={<Navigate to="/admin/overview" replace />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} handle={preload(loadNotFoundPage)} />
    </Route>
  </Route>
);
