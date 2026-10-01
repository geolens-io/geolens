import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import type { SettingItem } from '@/api/settings';
import { SettingsAITab } from '../SettingsAITab';

const hoisted = vi.hoisted(() => ({ apiFetch: vi.fn() }));

function settingsWrites() {
  return hoisted.apiFetch.mock.calls.filter(([, init]) => init?.method === 'PUT');
}

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, apiFetch: hoisted.apiFetch };
});

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: () => false }),
}));

vi.mock('@/hooks/use-settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-settings')>();
  return { ...actual, useApiKeyStatus: () => ({ data: { configured: true } }) };
});

const settings: SettingItem[] = [
  { key: 'semantic_search_enabled', value: false, source: 'default', label: 'Semantic search' },
  { key: 'llm_model', value: 'claude-3', source: 'default', label: 'Model' },
];

function renderTab(overrides: { envOnly?: boolean; onSave?: () => void } = {}) {
  const onSave = overrides.onSave ?? vi.fn();
  render(
    <SettingsAITab
      settings={settings}
      envOnly={overrides.envOnly ?? false}
      onSave={onSave}
      onReset={vi.fn()}
      isSaving={false}
    />,
  );
  return { onSave };
}

describe('SettingsAITab semantic search switch', () => {
  beforeEach(() => hoisted.apiFetch.mockReset());

  it('sends no request when flipped and marks the form unsaved', async () => {
    const user = userEvent.setup();
    renderTab();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

    await user.click(screen.getByRole('switch', { name: 'Semantic Search' }));

    expect(screen.getByRole('switch', { name: 'Semantic Search' })).toBeChecked();
    expect(settingsWrites()).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('saves the switch together with the other edited fields', async () => {
    const user = userEvent.setup();
    const { onSave } = renderTab();

    await user.click(screen.getByRole('switch', { name: 'Semantic Search' }));
    await user.type(screen.getByRole('textbox', { name: 'Model' }), '-x');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({
      semantic_search_enabled: true,
      llm_model: 'claude-3-x',
    });
  });

  it('restores the saved value on Discard Changes', async () => {
    const user = userEvent.setup();
    const { onSave } = renderTab();

    await user.click(screen.getByRole('switch', { name: 'Semantic Search' }));
    await user.click(screen.getByRole('button', { name: 'Discard Changes' }));

    expect(screen.getByRole('switch', { name: 'Semantic Search' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
    expect(settingsWrites()).toHaveLength(0);
  });

  it('is read-only when settings are env-only', () => {
    renderTab({ envOnly: true });
    expect(screen.getByRole('switch', { name: 'Semantic Search' })).toBeDisabled();
  });
});
