import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';

// builder-audit #338 STACK-03: the inline-rename state machine was duplicated
// near-verbatim between StackRow and FolderGroupRow — including the subtle
// blur-double-fire / committingRef / Radix onCloseAutoFocus focus-race logic
// that already required a BUG-03 follow-up fix. This hook is the single source.

interface UseInlineRenameOptions {
  /** Current display value — used as the initial edit value and the Escape revert target. */
  value: string;
  /** Commit handler. Receives the trimmed name, or null when the field is empty. */
  onCommit: (next: string | null) => void;
}

export function useInlineRename({ value, onCommit }: UseInlineRenameOptions) {
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState('');
  const escapeRef = useRef(false);
  const committingRef = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Gates Radix DropdownMenu's `restoreFocus` (onCloseAutoFocus) so the rename
  // input keeps focus after the kebab menu closes; without it Radix steals
  // focus back to the trigger in real browsers (jsdom did not exercise the race).
  const skipCloseAutoFocusRef = useRef(false);

  // Focus + select the rename input once React commits it. rAF defers past the
  // commit; the onCloseAutoFocus gate prevents Radix from re-stealing focus.
  useEffect(() => {
    if (editing) {
      requestAnimationFrame(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          inputRef.current.select();
        }
      });
    }
  }, [editing]);

  const startRename = useCallback(() => {
    setNameValue(value);
    setEditing(true);
  }, [value]);

  const commit = useCallback(() => {
    if (escapeRef.current) {
      escapeRef.current = false;
      return;
    }
    if (committingRef.current) return; // block blur double-fire after Enter
    committingRef.current = true;
    setEditing(false);
    onCommit(nameValue.trim() || null);
    // committingRef stays true during the synchronous blur triggered by
    // setEditing(false); reset it async so a later genuine focus+blur is allowed.
    requestAnimationFrame(() => {
      committingRef.current = false;
    });
  }, [nameValue, onCommit]);

  const inputHandlers = {
    onChange: (e: ChangeEvent<HTMLInputElement>) => setNameValue(e.target.value),
    onBlur: commit,
    onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        commit();
      }
      if (e.key === 'Escape') {
        escapeRef.current = true;
        setEditing(false);
        setNameValue(value);
      }
    },
    onClick: (e: MouseEvent<HTMLInputElement>) => e.stopPropagation(),
  };

  /** Pass to DropdownMenuContent's onCloseAutoFocus to keep focus on the input
   *  after the rename menu item closes the menu. */
  const handleMenuCloseAutoFocus = (e: Event) => {
    if (skipCloseAutoFocusRef.current) {
      e.preventDefault();
      skipCloseAutoFocusRef.current = false;
    }
  };

  return {
    editing,
    setEditing,
    nameValue,
    inputRef,
    inputHandlers,
    startRename,
    skipCloseAutoFocusRef,
    handleMenuCloseAutoFocus,
  };
}
