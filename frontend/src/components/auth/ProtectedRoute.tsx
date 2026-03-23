import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';

const SESSION_KEY = 'geolens-login-redirect';

export function ProtectedRoute() {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();

  if (!token) {
    const from = location.pathname + location.search;
    sessionStorage.setItem(SESSION_KEY, from);
    return <Navigate to="/login" replace state={{ from }} />;
  }

  return <Outlet />;
}
