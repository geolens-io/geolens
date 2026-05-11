import { Children, isValidElement, type ReactElement, type ReactNode } from 'react';
import { fireEvent, render, screen } from '@/test/test-utils';
import { BasemapAppearanceControls } from '../BasemapAppearanceControls';
import type { MapBasemapConfig } from '@/types/api';

type SelectChildProps = {
  children?: ReactNode;
  'aria-label'?: string;
};

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => {
    const childArray = Children.toArray(children);
    const trigger = childArray.find(
      (child): child is ReactElement<SelectChildProps> =>
        isValidElement<SelectChildProps>(child) && Boolean(child.props['aria-label']),
    );
    const content = childArray.find(
      (child): child is ReactElement<SelectChildProps> =>
        isValidElement<SelectChildProps>(child) && !child.props['aria-label'],
    );
    return (
      <select
        aria-label={trigger?.props['aria-label']}
        value={value ?? ''}
        onChange={(event) => onValueChange(event.currentTarget.value)}
      >
        {content?.props.children}
      </select>
    );
  },
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
}));

const VALUE: MapBasemapConfig = {
  label_mode: 'full',
  road_visibility: 'full',
  boundary_visibility: 'full',
  building_visibility: true,
  land_water_tone: 'default',
  relief_contrast: null,
};

describe('BasemapAppearanceControls', () => {
  it('normalizes legacy label visibility when basemap_config is missing', () => {
    render(
      <BasemapAppearanceControls
        value={null}
        showBasemapLabels={false}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('combobox', { name: 'Labels' })).toHaveValue('hidden');
    expect(screen.getByRole('combobox', { name: 'Roads' })).toHaveValue('full');
    expect(screen.getByRole('switch', { name: 'Buildings' })).toBeChecked();
  });

  it('emits curated config updates for sublayer controls', () => {
    const onChange = vi.fn();
    render(
      <BasemapAppearanceControls
        value={VALUE}
        showBasemapLabels
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'Roads' }), {
      target: { value: 'subtle' },
    });
    expect(onChange).toHaveBeenCalledWith({ ...VALUE, road_visibility: 'subtle' });

    fireEvent.click(screen.getByRole('switch', { name: 'Buildings' }));
    expect(onChange).toHaveBeenCalledWith({ ...VALUE, building_visibility: false });
  });

  it('keeps the compatibility label toggle aligned with label mode', () => {
    const onChange = vi.fn();
    const onShowBasemapLabelsChange = vi.fn();
    render(
      <BasemapAppearanceControls
        value={VALUE}
        showBasemapLabels
        onChange={onChange}
        onShowBasemapLabelsChange={onShowBasemapLabelsChange}
      />,
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'Labels' }), {
      target: { value: 'hidden' },
    });

    expect(onChange).toHaveBeenCalledWith({ ...VALUE, label_mode: 'hidden' });
    expect(onShowBasemapLabelsChange).toHaveBeenCalledWith(false);
  });
});
