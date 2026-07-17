/**
 * Generic admin-configured announcement banner.
 *
 * Renders for all visitors (logged-in or anonymous) when the admin has
 * enabled it AND set a non-empty banner_text in Settings → General. Color is
 * one of the theme tokens (warning | info | success | destructive); unknown
 * values fall back to warning.
 *
 * Dismissible per session: dismissing stores the banner text in
 * sessionStorage, so it stays hidden until the tab session ends or the admin
 * changes the text.
 *
 * Reuses the same /auth/config query-cache entry as DemoBanner — no
 * additional network request.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';

const COLOR_CLASSES: Record<string, string> = {
  warning: 'border-warning/30 bg-warning/10 text-warning',
  info: 'border-info/30 bg-info/10 text-info',
  success: 'border-success/30 bg-success/10 text-success',
  destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
};

const DISMISS_KEY = 'gl-site-banner-dismissed';

function getDismissed(): string | null {
  try {
    return sessionStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

export function SiteBanner() {
  const { t } = useTranslation('common');
  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });
  const [dismissed, setDismissed] = useState(getDismissed);

  const text = config?.banner_text?.trim();
  if (!config?.banner_enabled || !text || dismissed === text) return null;

  const colorClass = COLOR_CLASSES[config?.banner_color ?? ''] ?? COLOR_CLASSES.warning;

  function handleDismiss() {
    try {
      sessionStorage.setItem(DISMISS_KEY, text!);
    } catch {
      // storage unavailable (privacy mode) — dismiss for this mount only
    }
    setDismissed(text!);
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`relative border-b px-8 py-1.5 text-center text-sm ${colorClass}`}
    >
      {text}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={t('close')}
        className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-0.5 opacity-70 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
