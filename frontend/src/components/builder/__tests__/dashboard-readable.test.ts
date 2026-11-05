import { dashboardPayload } from '../dashboard-draft';
import type { WidgetInstance } from '@/components/widgets/contract';

const mocked = vi.hoisted(() => ({ reads: [] as string[] }));

vi.mock('@/components/widgets/registry', async (importActual) => ({
  ...(await importActual<typeof import('@/components/widgets/registry')>()),
  dashboardReadableTypes: () => mocked.reads,
}));

const text = {
  id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
  type: 'markdown',
  v: 1,
  config: { text: 'Notes' },
} as WidgetInstance;
const legacy = ['markdown:1', 'indicator:1', 'bar_chart:1', 'histogram:1', 'category_selector:1'];

describe('the widget types a save says it reads', () => {
  it('are left out while they match what a server assumes', () => {
    mocked.reads = [...legacy].reverse();
    expect(dashboardPayload({ panel: 'right', widgets: [text] }, [], { panel: 'right' })).not.toHaveProperty('readable');
  });

  it('are sent once this build reads more', () => {
    mocked.reads = [...legacy, 'pie_chart:1'];
    expect(dashboardPayload({ panel: 'right', widgets: [text] }, [], { panel: 'right' })?.readable).toEqual(mocked.reads);
  });
});
