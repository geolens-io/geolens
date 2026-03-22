import { useAIStatus } from '@/hooks/use-admin';

export function useAIAvailability() {
  const aiStatus = useAIStatus();

  return {
    ...aiStatus,
    isAIAvailable: Boolean(aiStatus.data?.enabled && aiStatus.data?.configured),
  };
}
