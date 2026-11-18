import { Navigate, Outlet, useLocation } from 'react-router';
import { LoadingState } from '@/components/layout/LoadingState';
import { useSessionRestore } from '@/lib/session-sync';
import { useAuthStore } from '@/stores/auth-store';
import { writeSessionStorage } from '@/lib/storage';

const SESSION_KEY = 'geolens-login-redirect';

export function ProtectedRoute() {
  const token = useAuthStore((s) => s.token);
  const restoring = useSessionRestore((s) => s.restoring);
  const location = useLocation();

  if (!token && restoring) return <LoadingState />;
  if (!token) {
    const from = location.pathname + location.search;
    // Storage can be denied during render. The destination also travels in
    // router state, so a failed convenience write must not block the redirect.
    writeSessionStorage(SESSION_KEY, from);
    return <Navigate to="/login" replace state={{ from }} />;
  }

  return <Outlet />;
}
