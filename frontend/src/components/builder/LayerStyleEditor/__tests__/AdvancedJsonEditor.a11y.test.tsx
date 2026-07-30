import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@/test/test-utils';
import { AdvancedJsonEditor } from '../AdvancedJsonEditor';

/**
 * fix(#921): validation errors were rendered in a bare div, so pressing Apply
 * told a screen-reader user nothing, and the disclosure triggers never reported
 * their expanded state.
 */
describe('AdvancedJsonEditor accessibility', () => {
  function open() {
    render(
      <AdvancedJsonEditor
        paint={{ 'fill-color': '#ff0000' }}
        layout={{}}
        onPaintChange={vi.fn()}
        onLayoutChange={vi.fn()}
        defaultOpen
        layerType="fill"
      />,
    );
    return screen.getByRole('button', { name: /paint/i });
  }

  it('announces a validation error and wires it to the textarea', () => {
    fireEvent.click(open());
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: JSON.stringify({ 'line-color': '#fff' }) } });
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(textarea).toHaveAttribute('aria-invalid', 'true');
    expect(textarea).toHaveAttribute('aria-describedby', alert.id);
  });

  it('reports the block disclosure state and controls its content', () => {
    const trigger = open();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const controlled = trigger.getAttribute('aria-controls')!;
    expect(document.getElementById(controlled)).not.toBeNull();
  });

  it('gives the outer Advanced JSON trigger an aria-controls target', () => {
    open();
    const outer = screen.getByRole('button', { name: /style\.advancedJson|advanced/i });
    expect(outer).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById(outer.getAttribute('aria-controls')!)).not.toBeNull();
  });
});
