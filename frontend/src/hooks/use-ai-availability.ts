import { useAIStatus } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';

export function useAIAvailability() {
  const aiStatus = useAIStatus();
  const { can } = usePermissions();

  return {
    ...aiStatus,
    isAIAvailable: Boolean(
      aiStatus.data?.enabled && aiStatus.data?.configured && can('use_ai_chat'),
    ),
  };
}
