import { render, screen } from '@/test/test-utils';
import type { ApiKeyStatusResponse, SettingItem } from '@/api/settings';
import { SettingsAITab } from '../SettingsAITab';

const hoisted = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  keyStatus: undefined as ApiKeyStatusResponse | undefined,
}));

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, apiFetch: hoisted.apiFetch };
});

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: () => false }),
}));

vi.mock('@/hooks/use-settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-settings')>();
  return { ...actual, useApiKeyStatus: () => ({ data: hoisted.keyStatus }) };
});

const settings: SettingItem[] = [
  { key: 'llm_provider', value: 'anthropic', source: 'default', label: 'LLM Provider' },
];

function renderWith(keyStatus: ApiKeyStatusResponse) {
  hoisted.keyStatus = keyStatus;
  render(
    <SettingsAITab settings={settings} envOnly={false} onSave={vi.fn()} onReset={vi.fn()} isSaving={false} />,
  );
}

describe('SettingsAITab Claude platform status', () => {
  it('shows Claude on a cloud platform as configured without an Anthropic key', () => {
    renderWith({ anthropic_configured: true, anthropic_platform: 'bedrock', openai_configured: false });

    expect(screen.getByText('Claude on Amazon Bedrock: configured')).toBeInTheDocument();
    expect(screen.queryByText('ANTHROPIC_API_KEY not set')).not.toBeInTheDocument();
  });

  it('shows an unconfigured cloud platform by name', () => {
    renderWith({ anthropic_configured: false, anthropic_platform: 'vertex', openai_configured: false });

    expect(screen.getByText('Claude on Google Vertex AI: not configured')).toBeInTheDocument();
  });

  it('keeps the API key line on the anthropic platform', () => {
    renderWith({ anthropic_configured: false, anthropic_platform: 'anthropic', openai_configured: false });

    expect(screen.getByText('ANTHROPIC_API_KEY not set')).toBeInTheDocument();
  });
});
