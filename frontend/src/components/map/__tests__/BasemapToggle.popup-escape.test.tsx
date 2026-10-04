import type { ReactNode } from 'react';
import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BasemapToggle } from '../BasemapToggle';
import { FeaturePopup } from '../FeaturePopup';

vi.mock('@vis.gl/react-maplibre', () => ({
  Popup: ({ children }: { children: ReactNode }) => <div data-testid="popup">{children}</div>,
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({
    data: [
      { id: 'positron', label: 'Positron', url: 'u1', enabled: true, is_preset: true },
      { id: 'dark', label: 'Dark', url: 'u2', enabled: true, is_preset: true },
    ],
  }),
}));

vi.mock('@/lib/basemap-utils', () => ({
  basemapThumbnail: (id: string) => `/thumbs/${id}.png`,
}));

describe('Escape with a feature popup and the basemap picker open', () => {
  it('closes the picker that holds focus first, and the popup on the next Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <>
        <FeaturePopup
          longitude={0}
          latitude={0}
          features={[{ properties: { a: 1 }, layerName: 'L', columnInfo: null, title: null, visibleFields: null }]}
          onClose={onClose}
        />
        <BasemapToggle value="positron" onChange={vi.fn()} />
      </>,
    );
    const trigger = screen.getByRole('button', { name: 'Change basemap' });
    await user.click(trigger);
    screen.getByRole('button', { name: 'Dark' }).focus();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('button', { name: 'Dark' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
