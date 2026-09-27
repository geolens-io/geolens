import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsStorageTab } from '../SettingsStorageTab';
import type { SettingItem } from '@/api/settings';

function renderStorage(bytes: number) {
  const onSave = vi.fn();
  const settings: SettingItem[] = [
    { key: 'max_storage_bytes_per_user', value: bytes, source: 'overridden', label: 'Storage' },
    { key: 'max_datasets_per_user', value: 0, source: 'default', label: 'Datasets' },
  ];
  render(<SettingsStorageTab settings={settings} envOnly={false} onSave={onSave} onReset={vi.fn()} isSaving={false} />);
  return { onSave };
}

describe('storage quota units', () => {
  beforeAll(() => {
    Element.prototype.hasPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('keeps a non-GiB byte limit exact when another field is saved', async () => {
    const user = userEvent.setup();
    const { onSave } = renderStorage(5_368_709_121);
    expect(screen.getByLabelText('Max storage per user')).toHaveValue(5_368_709_121);
    expect(screen.getByRole('combobox', { name: 'Storage unit' })).toHaveTextContent('Bytes');

    await user.clear(screen.getByLabelText('Max Datasets per User'));
    await user.type(screen.getByLabelText('Max Datasets per User'), '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ max_datasets_per_user: 7 });
  });

  it('retains an arbitrary byte limit when switching to GiB', async () => {
    const user = userEvent.setup();
    const { onSave } = renderStorage(5_368_709_121);

    await user.click(screen.getByRole('combobox', { name: 'Storage unit' }));
    await user.click(screen.getByRole('option', { name: 'GiB' }));
    expect((screen.getByLabelText('Max storage per user') as HTMLInputElement).value).toBe('5.000000000931322574615478515625');
    await user.clear(screen.getByLabelText('Max Datasets per User'));
    await user.type(screen.getByLabelText('Max Datasets per User'), '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ max_datasets_per_user: 7 });
  });

  it('converts a fractional GiB quota to an exact byte limit', async () => {
    const user = userEvent.setup();
    const { onSave } = renderStorage(0);
    const quantity = screen.getByLabelText('Max storage per user');
    expect(screen.getByRole('combobox', { name: 'Storage unit' })).toHaveTextContent('GiB');

    await user.clear(quantity);
    await user.type(quantity, '1.5');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ max_storage_bytes_per_user: 1_610_612_736 });
  });

  it('rejects a quantity that cannot be represented as whole bytes', async () => {
    const user = userEvent.setup();
    renderStorage(0);
    const quantity = screen.getByLabelText('Max storage per user');
    await user.clear(quantity);
    await user.type(quantity, '0.0000000001');

    expect(quantity).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});
