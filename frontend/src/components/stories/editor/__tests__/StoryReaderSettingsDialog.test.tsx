import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { StoryReaderSettingsDialog } from '../StoryReaderSettingsDialog';
import type { StorySettings } from '@/types/api';

const base: StorySettings = { navigation: false, layout: 'side', panel_position: 'left', theme: 'follow' };

function renderDialog(settings: StorySettings | null, onChange = vi.fn()) {
  render(<StoryReaderSettingsDialog settings={settings} open onOpenChange={vi.fn()} onChange={onChange} />);
  return onChange;
}

describe('StoryReaderSettingsDialog reader theme', () => {
  beforeAll(() => {
    // jsdom lacks the pointer APIs Radix Select reads when it opens.
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => undefined;
    Element.prototype.scrollIntoView ??= () => undefined;
  });

  it('shows the stored theme', () => {
    renderDialog({ ...base, theme: 'dark' });
    expect(screen.getByRole('combobox', { name: 'Reader theme' })).toHaveTextContent('Dark');
  });

  it('shows follow for a story without settings', () => {
    renderDialog(null);
    expect(screen.getByRole('combobox', { name: 'Reader theme' })).toHaveTextContent('Follow the reader');
  });

  it('reports the chosen theme', async () => {
    const user = userEvent.setup();
    const onChange = renderDialog(base);
    await user.click(screen.getByRole('combobox', { name: 'Reader theme' }));
    await user.click(await screen.findByRole('option', { name: 'Light' }));
    expect(onChange).toHaveBeenCalledWith({ theme: 'light' });
  });
});
