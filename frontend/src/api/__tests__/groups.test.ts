import { apiFetch } from '@/api/client';
import { listMyGroups } from '@/api/groups';

vi.mock('@/api/client', () => ({ apiFetch: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);

describe('listMyGroups', () => {
  it('reads every page so an admin sees all groups', async () => {
    const page = (start: number, count: number) =>
      Array.from({ length: count }, (_, i) => ({ id: `g${start + i}`, name: `Group ${start + i}` }));
    mockApiFetch
      .mockResolvedValueOnce({ groups: page(0, 200), total: 250 })
      .mockResolvedValueOnce({ groups: page(200, 50), total: 250 });

    const groups = await listMyGroups();

    expect(groups).toHaveLength(250);
    expect(mockApiFetch.mock.calls.map((c) => c[0])).toEqual([
      '/groups/mine/?skip=0&limit=200',
      '/groups/mine/?skip=200&limit=200',
    ]);
  });
});
