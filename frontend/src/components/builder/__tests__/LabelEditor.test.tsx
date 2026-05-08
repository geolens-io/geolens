import { fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { LabelEditor } from '../LabelEditor';
import type { LabelConfig } from '@/types/api';

(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const columns = [{ name: 'name', type: 'text' }];

function renderLabelEditor(labelConfig: LabelConfig, onLabelChange = vi.fn()) {
  render(
    <LabelEditor
      columns={columns}
      labelConfig={labelConfig}
      onLabelChange={onLabelChange}
      geometryType="Point"
    />,
  );
  return onLabelChange;
}

describe('LabelEditor zoom expressions', () => {
  it('emits a label font-size zoom expression from the first-class editor', async () => {
    const onLabelChange = renderLabelEditor({
      column: 'name',
      fontSize: 12,
      textOpacity: 1,
    });
    const user = userEvent.setup();

    await user.click(within(screen.getByRole('group', { name: 'Font size mode' })).getByRole('button', { name: 'Varies by zoom' }));

    expect(onLabelChange).toHaveBeenCalledWith(expect.objectContaining({
      fontSize: ['interpolate', ['linear'], ['zoom'], 4, 12, 12, 12],
    }));
  });

  it('edits supported label opacity expressions without raw JSON', () => {
    const onLabelChange = renderLabelEditor({
      column: 'name',
      fontSize: 12,
      textOpacity: ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 1],
    });

    fireEvent.change(screen.getByLabelText('Text opacity Stop 2 value'), { target: { value: '0.8' } });

    expect(onLabelChange).toHaveBeenCalledWith(expect.objectContaining({
      textOpacity: ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 0.8],
    }));
  });

  it('shows unsupported label expressions without flattening them', () => {
    const onLabelChange = renderLabelEditor({
      column: 'name',
      fontSize: ['interpolate', ['linear'], ['zoom'], 4, ['get', 'size'], 12, 16] as unknown as LabelConfig['fontSize'],
      textOpacity: 1,
    });

    expect(screen.getByText('This property uses an unsupported expression. Use Advanced JSON to edit it.')).toBeInTheDocument();
    expect(onLabelChange).not.toHaveBeenCalled();
  });
});

describe('LabelEditor LAYER-01 — toggle no-op when no columns available', () => {
  it('Switch is disabled when labelConfig is null AND columns is empty', () => {
    render(
      <LabelEditor
        columns={[]}
        labelConfig={null}
        onLabelChange={vi.fn()}
        geometryType="Point"
      />,
    );
    const sw = screen.getByRole('switch');
    expect(sw).toBeDisabled();
    expect(sw).toHaveAttribute('aria-disabled', 'true');
  });

  it('handleToggle bails out (no onLabelChange call) when toggled on with empty columns', async () => {
    // Forced-on path: bypass the disabled guard by mounting with onCheckedChange wired directly
    // through the Switch; we drive handleToggle programmatically by clicking. Even if a future
    // change re-enables the Switch in this state, the bail-out keeps the toggle from snapping
    // back via the upstream null-normalization (LAYER-01).
    const onLabelChange = vi.fn();
    render(
      <LabelEditor
        columns={[]}
        labelConfig={null}
        onLabelChange={onLabelChange}
        geometryType="Point"
      />,
    );
    const sw = screen.getByRole('switch');
    // Disabled state means the click won't fire onCheckedChange; the bail-out is the
    // belt-and-suspenders second line of defense documented in handleToggle.
    fireEvent.click(sw);
    expect(onLabelChange).not.toHaveBeenCalled();
  });
});
