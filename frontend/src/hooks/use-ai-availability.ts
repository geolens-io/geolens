import { useAIStatus } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';

export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const aiStatus = useAIStatus({ enabled: !!token });
  const { can } = usePermissions();

  return {
    ...aiStatus,
    isAIAvailable: Boolean(
      aiStatus.data?.enabled && aiStatus.data?.configured && can('use_ai_chat'),
    ),
  };
}
