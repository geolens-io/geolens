/**
 * DEMO-03 (Phase 1226): Demo-mode notice banner.
 *
 * Renders only when demo_mode=true AND a JWT token is present (logged-in).
 * Anonymous visitors never see the banner.
 * Self-hosters on the default config (demo_mode=false) see zero change.
 *
 * Reuses the same /auth/config query-cache entry that LandingFirstGuard
 * populates — no additional network request.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { useAuthStore } from '@/stores/auth-store';

export function DemoBanner() {
  const token = useAuthStore((s) => s.token);

  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  const demoMode = config?.demo_mode ?? false;

  if (!demoMode || !token) return null;

  return <DemoBannerInner />;
}

function DemoBannerInner() {
  const { t } = useTranslation('common');
  return (
    <div
      role="status"
      aria-live="polite"
      className="border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-center text-sm text-warning"
    >
      {t('demoBanner')}
    </div>
  );
}
