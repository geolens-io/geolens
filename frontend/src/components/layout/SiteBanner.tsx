/**
 * Generic admin-configured announcement banner.
 *
 * Renders for all visitors (logged-in or anonymous) whenever the admin has
 * set a non-empty banner_text in Settings → General. Color is one of the
 * theme tokens (warning | info | success | destructive); unknown values
 * fall back to warning.
 *
 * Reuses the same /auth/config query-cache entry as DemoBanner — no
 * additional network request.
 */
import { useQuery } from '@tanstack/react-query';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';

const COLOR_CLASSES: Record<string, string> = {
  warning: 'border-warning/30 bg-warning/10 text-warning',
  info: 'border-info/30 bg-info/10 text-info',
  success: 'border-success/30 bg-success/10 text-success',
  destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
};

export function SiteBanner() {
  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  const text = config?.banner_text?.trim();
  if (!text) return null;

  const colorClass = COLOR_CLASSES[config?.banner_color ?? ''] ?? COLOR_CLASSES.warning;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`border-b px-4 py-1.5 text-center text-sm ${colorClass}`}
    >
      {text}
    </div>
  );
}
