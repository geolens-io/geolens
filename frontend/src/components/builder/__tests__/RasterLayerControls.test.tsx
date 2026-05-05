import { fireEvent, render, screen } from '@/test/test-utils';
import type { ReactNode } from 'react';
import { RasterLayerControls } from '../RasterLayerControls';

vi.mock('@/components/ui/slider', () => ({
  Slider: ({
    value,
    min,
    max,
    step,
    onValueChange,
    'aria-label': ariaLabel,
  }: {
    value: number[];
    min: number;
    max: number;
    step: number;
    onValueChange: (value: number[]) => void;
    'aria-label': string;
  }) => (
    <input
      aria-label={ariaLabel}
      type="range"
      value={value[0]}
      min={min}
      max={max}
      step={step}
      onChange={(event) => onValueChange([Number(event.currentTarget.value)])}
    />
  ),
}));

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => (
    <select
      aria-label="Resampling"
      value={value}
      onChange={(event) => onValueChange(event.currentTarget.value)}
    >
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectValue: () => null,
}));

describe('RasterLayerControls', () => {
  it('renders first-class raster paint controls', () => {
    render(
      <RasterLayerControls
        paint={{
          'raster-brightness-min': 0.1,
          'raster-brightness-max': 0.9,
          'raster-contrast': 0.25,
          'raster-saturation': -0.2,
          'raster-hue-rotate': 180,
          'raster-fade-duration': 500,
          'raster-resampling': 'nearest',
        }}
        opacity={0.65}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('slider', { name: 'Brightness min' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Brightness max' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Contrast' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Saturation' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Hue' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Fade' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Opacity' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Resampling' })).toHaveValue('nearest');
  });

  it('writes raster paint changes without writing opacity into paint', () => {
    const onPaintChange = vi.fn();
    const onOpacityChange = vi.fn();
    render(
      <RasterLayerControls
        paint={{ 'raster-contrast': 0 }}
        opacity={0.5}
        onPaintChange={onPaintChange}
        onOpacityChange={onOpacityChange}
      />,
    );

    fireEvent.change(screen.getByRole('slider', { name: 'Contrast' }), { target: { value: '0.5' } });
    expect(onPaintChange).toHaveBeenCalledWith({ 'raster-contrast': 0.5 });

    fireEvent.change(screen.getByRole('combobox', { name: 'Resampling' }), { target: { value: 'nearest' } });
    expect(onPaintChange).toHaveBeenCalledWith({
      'raster-contrast': 0,
      'raster-resampling': 'nearest',
    });

    fireEvent.change(screen.getByRole('slider', { name: 'Opacity' }), { target: { value: '0.8' } });
    expect(onOpacityChange).toHaveBeenCalledWith(0.8);
    expect(onPaintChange).not.toHaveBeenCalledWith(expect.objectContaining({ 'raster-opacity': 0.8 }));
  });

  it('resets raster paint keys and restores full opacity', () => {
    const onPaintChange = vi.fn();
    const onOpacityChange = vi.fn();
    render(
      <RasterLayerControls
        paint={{
          'raster-brightness-min': 0.2,
          'raster-brightness-max': 0.8,
          'raster-contrast': 0.4,
          'raster-saturation': 0.3,
          'raster-hue-rotate': 45,
          'raster-resampling': 'nearest',
          'raster-fade-duration': 100,
          'custom-keep': true,
        }}
        opacity={0.45}
        onPaintChange={onPaintChange}
        onOpacityChange={onOpacityChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /reset/i }));

    expect(onPaintChange).toHaveBeenCalledWith({ 'custom-keep': true });
    expect(onOpacityChange).toHaveBeenCalledWith(1);
  });
});
