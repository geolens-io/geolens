import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { writeSessionStorage } from '@/lib/storage';

const SESSION_KEY = 'geolens-login-redirect';

export function ProtectedRoute() {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();

  if (!token) {
    const from = location.pathname + location.search;
    // fix(#1527): this write happens during render, and every protected route
    // in the app is behind it. In a storage-denied context the bare setItem
    // threw and the redirect became a blank page; the `from` also rides
    // router state, so losing the key costs nothing.
    writeSessionStorage(SESSION_KEY, from);
    return <Navigate to="/login" replace state={{ from }} />;
  }

  return <Outlet />;
}
