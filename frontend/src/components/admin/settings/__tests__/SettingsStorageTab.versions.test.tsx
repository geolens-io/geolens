import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsStorageTab } from '../SettingsStorageTab';
import { getCatalogStats } from '@/api/admin';
import type { SettingItem } from '@/api/settings';
import type { CatalogStatsResponse } from '@/types/api';

vi.mock('@/api/admin', () => ({ getCatalogStats: vi.fn() }));

const settings: SettingItem[] = [
  { key: 'previous_versions_kept', value: 3, source: 'default', label: 'Kept' },
];

describe('previous versions kept', () => {
  it('shows the kept count and the storage kept versions use, and saves a new count', async () => {
    vi.mocked(getCatalogStats).mockResolvedValue({
      previous_versions_bytes: 5 * 1024 * 1024,
    } as CatalogStatsResponse);
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <SettingsStorageTab settings={settings} envOnly={false} onSave={onSave} onReset={vi.fn()} isSaving={false} />,
    );

    const field = screen.getByLabelText('Previous versions kept per dataset');
    expect(field).toHaveValue(3);
    expect(await screen.findByText('Kept versions currently use 5 MB.')).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, '5');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ previous_versions_kept: 5 });
  });
});
