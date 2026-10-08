import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from './sheet';

function Harness({ modal, overlay }: { modal?: boolean; overlay?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" data-testid="map">map</button>
      <Sheet open={open} onOpenChange={setOpen} modal={modal}>
        <SheetTrigger>open sheet</SheetTrigger>
        <SheetContent overlay={overlay}>
          <SheetTitle>Style</SheetTitle>
          <SheetDescription>Edit</SheetDescription>
          <input aria-label="field" />
        </SheetContent>
      </Sheet>
    </div>
  );
}

describe('SheetContent without an overlay', () => {
  it('renders no overlay, keeps the page clickable, and closes on Escape with focus returned', async () => {
    const user = userEvent.setup();
    render(<Harness modal={false} overlay={false} />);
    const trigger = screen.getByText('open sheet');
    await user.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="sheet-overlay"]')).toBeNull();
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);

    await user.click(screen.getByTestId('map'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it('still renders the overlay by default', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText('open sheet'));
    expect(document.querySelector('[data-slot="sheet-overlay"]')).not.toBeNull();
  });
});
