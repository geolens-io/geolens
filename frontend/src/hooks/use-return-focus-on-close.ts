import { useCallback, useState } from 'react';

type CloseAutoFocusHandler = (event: Event) => void;

/**
 * Radix returns focus on close only to a `Dialog.Trigger`. Dialogs opened from a
 * plain button or a menu item have none, so focus would fall to <body>. This
 * remembers the element focused when the content mounted and restores it. A
 * focused menu item unmounts with its menu, so its trigger stands in.
 */
function findOpener(): HTMLElement | null {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active === document.body) return null;
  const triggerId = active.closest('[role="menu"]')?.getAttribute('aria-labelledby');
  return (triggerId && document.getElementById(triggerId)) || active;
}

export function useReturnFocusOnClose(onCloseAutoFocus?: CloseAutoFocusHandler) {
  const [opener] = useState(findOpener);

  return useCallback(
    (event: Event) => {
      onCloseAutoFocus?.(event);
      if (event.defaultPrevented || !opener?.isConnected) return;
      event.preventDefault();
      opener.focus();
    },
    [opener, onCloseAutoFocus],
  );
}
