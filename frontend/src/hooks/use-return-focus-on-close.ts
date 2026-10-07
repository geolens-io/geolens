import { useCallback, useRef } from 'react';

type FocusEventHandler = (event: Event) => void;

function findOpener(): HTMLElement | null {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active === document.body) return null;
  const triggerId = active.closest('[role="menu"]')?.getAttribute('aria-labelledby');
  return (triggerId && document.getElementById(triggerId)) || active;
}

/**
 * Radix returns focus on close only to a `Dialog.Trigger`. Dialogs opened from a
 * plain button or a menu item have none, so focus would fall to <body>. This
 * records the focused element each time the dialog opens and restores it on
 * close. A focused menu item unmounts with its menu, so its trigger stands in.
 */
export function useReturnFocusOnClose(
  onOpenAutoFocus?: FocusEventHandler,
  onCloseAutoFocus?: FocusEventHandler,
) {
  const opener = useRef<HTMLElement | null>(null);

  const handleOpen = useCallback(
    (event: Event) => {
      opener.current = findOpener();
      onOpenAutoFocus?.(event);
    },
    [onOpenAutoFocus],
  );

  const handleClose = useCallback(
    (event: Event) => {
      onCloseAutoFocus?.(event);
      const target = opener.current;
      opener.current = null;
      if (event.defaultPrevented || !target?.isConnected) return;
      event.preventDefault();
      target.focus();
    },
    [onCloseAutoFocus],
  );

  return { onOpenAutoFocus: handleOpen, onCloseAutoFocus: handleClose };
}
