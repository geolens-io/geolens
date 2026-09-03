// fix(#1778): the HexColorInput in both SwatchColorPopover and
// StyleColorPicker had no accessible name -- it only renders inside an
// open popover, so the gating axe suite structurally cannot reach it.
import { fireEvent, render, screen } from '@/test/test-utils';
import { StyleColorPicker, SwatchColorPopover } from '../StyleColorPicker';

describe('StyleColorPicker / SwatchColorPopover hex input accessible names (#1778)', () => {
  it('names the hex input in StyleColorPicker from the field label', () => {
    render(<StyleColorPicker label="Fill" color="#ff0000" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Fill' }));

    expect(screen.getByLabelText('Fill hex value')).toBeInTheDocument();
  });

  it('names the hex input in SwatchColorPopover from the provided label', () => {
    render(<SwatchColorPopover label="Category A" color="#00ff00" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Category A' }));

    expect(screen.getByLabelText('Category A hex value')).toBeInTheDocument();
  });

  it('falls back to a generic label when SwatchColorPopover has none', () => {
    render(<SwatchColorPopover color="#0000ff" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '#0000ff' }));

    expect(screen.getByLabelText('Hex color value')).toBeInTheDocument();
  });
});
