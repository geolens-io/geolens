import { renderHook, waitFor } from '@/test/test-utils';
import { useUserNames } from '@/hooks/use-admin';

const mockListUserNames = vi.fn();
vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>();
  return { ...actual, listUserNames: () => mockListUserNames() };
});

it('does not request manage-users names until the lookup is enabled', async () => {
  mockListUserNames.mockResolvedValue([]);
  const { result, rerender } = renderHook(({ enabled }) => useUserNames({ enabled }), {
    initialProps: { enabled: false },
  });

  expect(result.current.fetchStatus).toBe('idle');
  expect(mockListUserNames).not.toHaveBeenCalled();

  rerender({ enabled: true });
  await waitFor(() => expect(mockListUserNames).toHaveBeenCalledOnce());
});
