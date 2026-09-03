// fix(#1778): semantic_search_rate_limit and basemap_proxy_rate_limit
// register on tab="network" and their docstrings say the admin Settings UI
// is the only control (neither has an env var), but this tab never read
// either key, so an operator could not tighten the SEC-S11 embedding
// cost-DoS cap or the SEC-S10 commercial-key replay cap without a raw PUT.
import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsNetworkTab } from '../SettingsNetworkTab';
import type { SettingItem } from '@/api/settings';

vi.mock('@/hooks/use-settings', () => ({
  useNotificationStatus: () => ({ data: undefined, isLoading: false }),
  useSendTestNotification: () => ({ mutate: vi.fn(), isPending: false }),
}));

function makeSetting(key: string, value: unknown): SettingItem {
  return { key, value, source: 'overridden', label: key };
}

function renderTab(overrides: Partial<Parameters<typeof SettingsNetworkTab>[0]> = {}) {
  const settings: SettingItem[] = [
    makeSetting('cors_allowed_origins', ''),
    makeSetting('global_rate_limit', 60),
    makeSetting('ogc_items_max_page_size', 1000),
    makeSetting('semantic_search_rate_limit', 30),
    makeSetting('basemap_proxy_rate_limit', 120),
  ];
  const onDirtyChange = vi.fn();
  render(
    <SettingsNetworkTab
      settings={settings}
      envOnly={false}
      onSave={vi.fn()}
      onReset={vi.fn()}
      isSaving={false}
      onDirtyChange={onDirtyChange}
      {...overrides}
    />,
  );
  return { onDirtyChange };
}

describe('SettingsNetworkTab rate limit fields (#1778)', () => {
  it('renders and edits the semantic search rate limit', async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderTab();

    const input = screen.getByLabelText(/semantic search rate limit/i);
    expect(input).toHaveValue(30);

    await user.clear(input);
    await user.type(input, '5');

    expect(onDirtyChange).toHaveBeenCalledWith(true);
  });

  it('renders and edits the basemap proxy rate limit', async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderTab();

    const input = screen.getByLabelText(/basemap proxy rate limit/i);
    expect(input).toHaveValue(120);

    await user.clear(input);
    await user.type(input, '90');

    expect(onDirtyChange).toHaveBeenCalledWith(true);
  });
});
