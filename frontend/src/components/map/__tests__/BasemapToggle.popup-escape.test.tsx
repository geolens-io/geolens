import { useState, type ReactNode } from 'react';
import { act, render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BasemapToggle } from '../BasemapToggle';
import { FeaturePopup } from '../FeaturePopup';
import { LayerLegend } from '@/components/viewer/LayerLegend';

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

function LegendHarness() {
  const [open, setOpen] = useState(false);
  return (
    <LayerLegend
      layers={[]}
      visibleLayers={new Set()}
      onToggleVisibility={vi.fn()}
      isOpen={open}
      onToggle={() => setOpen((v) => !v)}
    />
  );
}

function renderAll(onClose: () => void, onChange: (id: string) => void = vi.fn()) {
  return render(
    <>
      <FeaturePopup
        longitude={0}
        latitude={0}
        features={[{ properties: { a: 1 }, layerName: 'L', columnInfo: null, title: null, visibleFields: null }]}
        onClose={onClose}
      />
      <BasemapToggle value="positron" onChange={onChange} />
      <button type="button">elsewhere</button>
      <LegendHarness />
    </>,
  );
}

const openPicker = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: 'Change basemap' }));
const darkOption = () => screen.queryByRole('button', { name: 'Dark' });

describe('Escape with a feature popup, the basemap picker and the legend', () => {
  it('closes the picker that holds focus and leaves the popup open, then the popup on the next Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderAll(onClose);
    const trigger = screen.getByRole('button', { name: 'Change basemap' });
    await openPicker(user);
    screen.getByRole('button', { name: 'Dark' }).focus();

    await user.keyboard('{Escape}');

    expect(darkOption()).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes the picker when focus leaves it, without moving focus; Escape then closes the popup', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderAll(onClose);
    await openPicker(user);
    const elsewhere = screen.getByRole('button', { name: 'elsewhere' });
    act(() => elsewhere.focus());

    expect(darkOption()).not.toBeInTheDocument();
    expect(document.activeElement).toBe(elsewhere);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('lets the legend own Escape after focus moved from the picker to it', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderAll(onClose);
    await openPicker(user);
    // Keyboard only (Shift+Tab equivalent): a mouse click would also trip the outside-click close.
    act(() => screen.getByRole('button', { name: /show legend/i }).focus());
    expect(darkOption()).not.toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('region')).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps the picker open for a click on its padding and still registers a mouse choice', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderAll(vi.fn(), onChange);
    await openPicker(user);

    await user.click(screen.getByRole('group', { name: 'Change basemap' }));
    expect(darkOption()).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Dark' }));
    expect(onChange).toHaveBeenCalledWith('dark');
    expect(darkOption()).not.toBeInTheDocument();
  });
});
