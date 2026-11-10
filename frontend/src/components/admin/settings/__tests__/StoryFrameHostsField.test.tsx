import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsNetworkTab } from '../SettingsNetworkTab';
import type { SettingItem } from '@/api/settings';

vi.mock('@/hooks/use-settings', () => ({
  useNotificationStatus: () => ({ data: undefined, isLoading: false }),
  useSendTestNotification: () => ({ mutate: vi.fn(), isPending: false }),
}));

function renderTab(hosts: unknown, envOnly = false) {
  const onSave = vi.fn();
  const settings: SettingItem[] = [{ key: 'story_frame_hosts', value: hosts, source: 'default', label: 'Story hosts' }];
  render(
    <SettingsNetworkTab settings={settings} envOnly={envOnly} onSave={onSave} onReset={vi.fn()} isSaving={false} />,
  );
  return { onSave };
}

it('says the blocks are off while no host is listed', () => {
  renderTab([]);
  expect(screen.getByText(/No sites yet, so embed and video blocks are off/)).toBeInTheDocument();
  expect(screen.getByText('Pages already open pick up the list after a reload.')).toBeInTheDocument();
});

it('adds an exact host, opts it into its own origin and saves the list', async () => {
  const user = userEvent.setup();
  const { onSave } = renderTab([{ host: 'video.example.net', allow_same_origin: false }]);
  const input = screen.getByRole('textbox', { name: 'Site host name' });
  const add = screen.getByRole('button', { name: 'Add site' });

  for (const bad of ['*.example.org', 'https://media.example.org', 'media.example.org/path', '10.0.0.1']) {
    await user.clear(input);
    await user.type(input, bad);
    expect(screen.getByText(/Enter a host name such as media.example.org/), bad).toBeInTheDocument();
    expect(add).toBeDisabled();
  }
  await user.clear(input);
  await user.type(input, 'Video.Example.net');
  expect(screen.getByText('That site is already on the list.')).toBeInTheDocument();

  await user.clear(input);
  await user.type(input, 'Media.Example.org{Enter}');
  expect(input).toHaveValue('');
  expect(screen.getAllByRole('switch')).toHaveLength(2);
  await user.click(screen.getByRole('switch', { name: "Keep the site's origin media.example.org" }));
  await user.click(screen.getByRole('button', { name: 'Remove video.example.net' }));
  await user.click(screen.getByRole('button', { name: 'Save' }));

  expect(onSave).toHaveBeenCalledWith({
    story_frame_hosts: [{ host: 'media.example.org', allow_same_origin: true }],
  });
});

it('is read-only when configuration is locked to the environment', () => {
  renderTab([{ host: 'media.example.org', allow_same_origin: false }], true);
  expect(screen.getByRole('textbox', { name: 'Site host name' })).toBeDisabled();
  expect(screen.getByRole('switch', { name: "Keep the site's origin media.example.org" })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Remove media.example.org' })).toBeDisabled();
});
