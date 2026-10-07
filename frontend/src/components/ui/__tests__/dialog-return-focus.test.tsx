import { useState } from 'react';
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '../alert-dialog';

describe('dialog focus return', () => {
  it('restores the element focused at open time, not at first mount', async () => {
    const user = userEvent.setup();
    function Gate() {
      const [mounted, setMounted] = useState(false);
      return (
        <div>
          <button onClick={() => setMounted(true)}>Mount</button>
          {mounted && (
            <AlertDialog>
              <AlertDialogTrigger>Open</AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogTitle>t</AlertDialogTitle>
                <AlertDialogDescription>d</AlertDialogDescription>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      );
    }
    render(<Gate />);
    await user.click(screen.getByRole('button', { name: 'Mount' }));
    const trigger = screen.getByRole('button', { name: 'Open' });

    await user.click(trigger);
    await user.keyboard('{Escape}');

    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
