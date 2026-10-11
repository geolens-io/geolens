import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { retrySessionRestore, useSessionRestore } from '@/lib/session-sync';
import { useAuthStore } from '@/stores/auth-store';

const TOAST_ID = 'session-restore';

/**
 * Says so while a reload's session could not get a token, instead of leaving
 * the stored user's name on a page that loaded without their access.
 */
export function SessionRestoreNotice() {
  const { t } = useTranslation('auth');
  const queryClient = useQueryClient();
  const failures = useSessionRestore((s) => s.failures);
  const token = useAuthStore((s) => s.token);
  const hasUser = useAuthStore((s) => s.user !== null);

  useEffect(() => {
    if (failures === 0) return;
    if (token || !hasUser) {
      useSessionRestore.setState({ failures: 0 });
      toast.dismiss(TOAST_ID);
      // Queries that ran without the token cached anonymous results.
      if (token) void queryClient.invalidateQueries();
      return;
    }
    toast.warning(t('sessionRestore.title'), {
      id: TOAST_ID,
      description: t('sessionRestore.body'),
      duration: Infinity,
      action: { label: t('sessionRestore.retry'), onClick: retrySessionRestore },
    });
  }, [failures, token, hasUser, queryClient, t]);

  return null;
}
