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

  it('keeps a draft when the block is collapsed and reopened', () => {
    const trigger = open();
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '{"fill-color": "#00ff00"' },
    });
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(screen.getByRole('textbox')).toHaveValue('{"fill-color": "#00ff00"');
  });

  it('discards the draft on an explicit Cancel', () => {
    const trigger = open();
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '{"nope"' } });
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    fireEvent.click(trigger);
    expect(screen.getByRole('textbox')).toHaveValue(JSON.stringify({ 'fill-color': '#ff0000' }, null, 2));
  });

  it('keeps every aria-controls target mounted while collapsed', () => {
    const trigger = open();
    // Collapsed block: the referenced element must still exist.
    expect(document.getElementById(trigger.getAttribute('aria-controls')!)).not.toBeNull();
    const outer = screen.getByRole('button', { name: /advanced json/i });
    fireEvent.click(outer);
    expect(document.getElementById(outer.getAttribute('aria-controls')!)).not.toBeNull();
  });

  it('gives the outer Advanced JSON trigger an aria-controls target', () => {
    open();
    const outer = screen.getByRole('button', { name: /advanced json/i });
    expect(outer).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById(outer.getAttribute('aria-controls')!)).not.toBeNull();
  });
});
