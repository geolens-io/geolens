import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsGeneralTab } from '../SettingsGeneralTab';
import type { SettingItem } from '@/api/settings';

function renderGeneral(retention: number | null) {
  const onSave = vi.fn();
  const settings: SettingItem[] = [
    { key: 'audit_retention_days', value: retention, source: 'default', label: 'Audit retention' },
  ];
  render(<SettingsGeneralTab settings={settings} envOnly={false} onSave={onSave} onReset={vi.fn()} isSaving={false} />);
  return { onSave };
}

describe('audit retention field', () => {
  it('starts empty when records are kept forever', () => {
    renderGeneral(null);
    const field = screen.getByLabelText('Audit log retention (days)');
    expect(field).toHaveValue(null);
    expect(field).toHaveAccessibleDescription(
      expect.stringMatching(/^Audit records older than this many days are deleted automatically\./),
    );
  });

  it('saves a whole number of days', async () => {
    const user = userEvent.setup();
    const { onSave } = renderGeneral(null);

    await user.type(screen.getByLabelText('Audit log retention (days)'), '90');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ audit_retention_days: 90 });
  });

  it('saves null when the field is cleared', async () => {
    const user = userEvent.setup();
    const { onSave } = renderGeneral(180);

    await user.clear(screen.getByLabelText('Audit log retention (days)'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ audit_retention_days: null });
  });

  it('warns below a year without blocking the save', async () => {
    const user = userEvent.setup();
    const { onSave } = renderGeneral(null);
    const field = screen.getByLabelText('Audit log retention (days)');

    await user.type(field, '364');
    expect(screen.getByText(/at least 365 days/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).toHaveBeenCalledWith({ audit_retention_days: 364 });

    await user.clear(field);
    await user.type(field, '365');
    expect(screen.queryByText(/at least 365 days/)).not.toBeInTheDocument();
  });

  it('rejects a value under the minimum and disables saving', async () => {
    const user = userEvent.setup();
    renderGeneral(null);
    const field = screen.getByLabelText('Audit log retention (days)');

    await user.type(field, '89');

    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field).toHaveAccessibleDescription(
      expect.stringMatching(/^Enter a whole number of days .* Audit records older than this many days/),
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('rejects a value above the maximum', async () => {
    const user = userEvent.setup();
    renderGeneral(null);
    const field = screen.getByLabelText('Audit log retention (days)');

    await user.type(field, '36501');

    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});
