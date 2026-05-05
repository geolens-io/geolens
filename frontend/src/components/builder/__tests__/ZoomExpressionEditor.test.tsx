import { fireEvent, render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ZoomExpressionEditor } from '../ZoomExpressionEditor';

(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

describe('ZoomExpressionEditor', () => {
  it('emits scalar values in fixed mode', () => {
    const onChange = vi.fn();
    render(
      <ZoomExpressionEditor
        label="Width"
        value={2}
        defaultValue={2}
        min={0.5}
        max={20}
        step={0.5}
        format="px"
        onChange={onChange}
      />,
    );

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Width' }), { key: 'ArrowRight' });

    expect(onChange).toHaveBeenCalledWith(2.5);
  });

  it('switches to zoom mode and emits a supported expression', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ZoomExpressionEditor
        label="Width"
        value={2}
        defaultValue={2}
        min={0.5}
        max={20}
        step={0.5}
        format="px"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Varies by zoom' }));

    expect(onChange).toHaveBeenCalledWith(['interpolate', ['linear'], ['zoom'], 4, 2, 12, 2]);
  });

  it('edits stop rows and emits valid zoom expressions', () => {
    const onChange = vi.fn();
    render(
      <ZoomExpressionEditor
        label="Radius"
        value={['interpolate', ['linear'], ['zoom'], 4, 3, 12, 9]}
        defaultValue={5}
        min={1}
        max={30}
        step={1}
        format="px"
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText('Radius Stop 2 value'), { target: { value: '12' } });

    expect(onChange).toHaveBeenCalledWith(['interpolate', ['linear'], ['zoom'], 4, 3, 12, 12]);
  });

  it('shows validation errors and does not emit malformed stop lists', () => {
    const onChange = vi.fn();
    render(
      <ZoomExpressionEditor
        label="Opacity"
        value={['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 1]}
        defaultValue={1}
        min={0}
        max={1}
        step={0.05}
        format="percent"
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText('Opacity Stop 2 zoom'), { target: { value: '3' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Zoom stops must be in ascending order.');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('can switch to step expressions and edit the base value', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ZoomExpressionEditor
        label="Width"
        value={['interpolate', ['linear'], ['zoom'], 4, 2, 12, 6]}
        defaultValue={2}
        min={0.5}
        max={20}
        step={0.5}
        format="px"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Step' }));
    fireEvent.change(screen.getByLabelText('Width Base value'), { target: { value: '1.5' } });

    expect(onChange).toHaveBeenLastCalledWith(['step', ['zoom'], 1.5, 10, 2]);
  });

  it('shows unsupported expression copy without flattening the value', () => {
    const onChange = vi.fn();
    render(
      <ZoomExpressionEditor
        label="Width"
        value={['interpolate', ['linear'], ['zoom'], 4, ['get', 'width'], 12, 6]}
        defaultValue={2}
        min={0.5}
        max={20}
        step={0.5}
        format="px"
        onChange={onChange}
      />,
    );

    expect(screen.getByText('This property uses an unsupported expression. Use Advanced JSON to edit it.')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
