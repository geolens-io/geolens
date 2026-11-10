import { useAuthStore } from '@/stores/auth-store';

const signedInAs = () => useAuthStore.getState().user?.id ?? null;

/**
 * Returns a check that the account signed in now is still the one signed in.
 * Another account signing in clears the query cache (wireAuthCacheReset), so a
 * story write that started before must drop its response rather than put the
 * first account's data back into the second's cache or screen.
 */
export function captureAccount(): () => boolean {
  const account = signedInAs();
  return () => signedInAs() === account;
}
