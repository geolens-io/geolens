import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ColorRampPicker } from '../ColorRampPicker';

// ColorRampPicker is a pure-UI component that depends on:
//   - color-ramps (real, no mock needed)
//   - i18n (provided by test-utils wrapper)
// No external API calls — no mocks required.

describe('ColorRampPicker — Reverse toggle', () => {
  it('renders the Reverse checkbox', () => {
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
        reversed={false}
        onReversedChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('reverse-ramp-toggle')).toBeInTheDocument();
  });

  it('calls onReversedChange(true) when Reverse is toggled on', async () => {
    const user = userEvent.setup();
    const onReversedChange = vi.fn();
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
        reversed={false}
        onReversedChange={onReversedChange}
      />,
    );
    await user.click(screen.getByTestId('reverse-ramp-toggle'));
    expect(onReversedChange).toHaveBeenCalledWith(true);
  });

  it('calls onReversedChange(false) when Reverse is untoggled', async () => {
    const user = userEvent.setup();
    const onReversedChange = vi.fn();
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
        reversed={true}
        onReversedChange={onReversedChange}
      />,
    );
    await user.click(screen.getByTestId('reverse-ramp-toggle'));
    expect(onReversedChange).toHaveBeenCalledWith(false);
  });

  it('reflects reversed=true in the checkbox checked state', () => {
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
        reversed={true}
        onReversedChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('reverse-ramp-toggle')).toBeChecked();
  });

  it('reflects reversed=false in the checkbox unchecked state', () => {
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
        reversed={false}
        onReversedChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('reverse-ramp-toggle')).not.toBeChecked();
  });
});

describe('ColorRampPicker — CVD-safe filter', () => {
  it('renders the CVD-safe toggle checkbox', () => {
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
      />,
    );
    expect(screen.getByTestId('cvd-safe-toggle')).toBeInTheDocument();
  });

  it('Spectral ramp is visible before enabling CVD-safe filter', () => {
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
      />,
    );
    expect(screen.getByRole('button', { name: 'Spectral' })).toBeInTheDocument();
  });

  it('Spectral ramp is hidden after enabling CVD-safe filter', async () => {
    const user = userEvent.setup();
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
      />,
    );
    await user.click(screen.getByTestId('cvd-safe-toggle'));
    expect(screen.queryByRole('button', { name: 'Spectral' })).not.toBeInTheDocument();
  });

  it('RdYlGn ramp is hidden after enabling CVD-safe filter', async () => {
    const user = userEvent.setup();
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
      />,
    );
    await user.click(screen.getByTestId('cvd-safe-toggle'));
    expect(screen.queryByRole('button', { name: 'Red-Yellow-Green' })).not.toBeInTheDocument();
  });

  it('Viridis ramp is still visible after enabling CVD-safe filter', async () => {
    const user = userEvent.setup();
    render(
      <ColorRampPicker
        rampName="Blues"
        onChange={vi.fn()}
        mode="graduated"
      />,
    );
    await user.click(screen.getByTestId('cvd-safe-toggle'));
    expect(screen.getByRole('button', { name: 'Viridis' })).toBeInTheDocument();
  });

  it('Set1 ramp is hidden after enabling CVD-safe filter (categorical mode)', async () => {
    const user = userEvent.setup();
    render(
      <ColorRampPicker
        rampName="Set2"
        onChange={vi.fn()}
        mode="categorical"
      />,
    );
    await user.click(screen.getByTestId('cvd-safe-toggle'));
    expect(screen.queryByRole('button', { name: 'Set 1' })).not.toBeInTheDocument();
  });

  it('Set2 ramp is still visible after enabling CVD-safe filter (categorical mode)', async () => {
    const user = userEvent.setup();
    render(
      <ColorRampPicker
        rampName="Set2"
        onChange={vi.fn()}
        mode="categorical"
      />,
    );
    await user.click(screen.getByTestId('cvd-safe-toggle'));
    expect(screen.getByRole('button', { name: 'Set 2' })).toBeInTheDocument();
  });
});
