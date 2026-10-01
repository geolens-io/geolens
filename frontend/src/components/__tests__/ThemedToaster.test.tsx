import { act, render } from '@/test/test-utils';
import { changeTestLanguage } from '@/test/i18n';
import { ThemedToaster } from '@/components/ThemedToaster';

afterEach(async () => {
  await changeTestLanguage('en');
});

function regionLabel() {
  return document.querySelector('section[aria-label]')?.getAttribute('aria-label');
}

describe('ThemedToaster', () => {
  it('labels the notification region in the active language and keeps the hotkey hint', async () => {
    render(<ThemedToaster />);
    expect(regionLabel()).toMatch(/^Notifications /);

    await act(() => changeTestLanguage('es'));
    expect(regionLabel()).toMatch(/^Notificaciones /);

    await act(() => changeTestLanguage('zh'));
    expect(regionLabel()).toMatch(/^通知 /);
  });
});
