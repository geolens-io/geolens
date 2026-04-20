import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';

interface InlineEditProps {
  value: string;
  onSave: (newValue: string) => void | Promise<void>;
  as?: 'h1' | 'h2' | 'p' | 'span';
  multiline?: boolean;
  className?: string;
  placeholder?: string;
  canEdit?: boolean;
  onDirtyChange?: (isDirty: boolean) => void;
  /** Start in edit mode immediately (e.g. after clicking "Add" CTA). */
  initialEditing?: boolean;
}

export function InlineEdit({
  value,
  onSave,
  as: Tag = 'span',
  multiline = false,
  className,
  placeholder = '',
  canEdit = true,
  onDirtyChange,
  initialEditing = false,
}: InlineEditProps) {
  const [editing, setEditing] = useState(initialEditing);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const isDirtyRef = useRef(false);

  const emitDirtyChange = useCallback(
    (nextIsDirty: boolean) => {
      if (!onDirtyChange || isDirtyRef.current === nextIsDirty) {
        return;
      }
      isDirtyRef.current = nextIsDirty;
      onDirtyChange(nextIsDirty);
    },
    [onDirtyChange],
  );

  const computeDirty = useCallback(
    (nextDraft: string) => nextDraft.trim() !== value.trim(),
    [value],
  );

  // Sync draft with external value when not editing
  useEffect(() => {
    if (!editing) {
      setDraft(value);
      emitDirtyChange(false);
    }
  }, [value, editing, emitDirtyChange]);

  // Focus input after entering edit mode, using requestAnimationFrame
  // to avoid the activation click triggering an immediate blur
  useEffect(() => {
    if (editing) {
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        // Select all text for easy replacement
        inputRef.current?.select();
      });
    }
  }, [editing]);

  const save = useCallback(async () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      await onSave(trimmed);
    }
    emitDirtyChange(false);
    setEditing(false);
  }, [draft, value, onSave, emitDirtyChange]);

  const cancel = useCallback(() => {
    setDraft(value);
    emitDirtyChange(false);
    setEditing(false);
  }, [value, emitDirtyChange]);

  const handleDraftChange = useCallback(
    (nextDraft: string) => {
      setDraft(nextDraft);
      emitDirtyChange(computeDirty(nextDraft));
    },
    [computeDirty, emitDirtyChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        cancel();
      }
      if (e.key === 'Enter' && !multiline) {
        e.preventDefault();
        save();
      }
      // For multiline, Enter inserts a newline; Ctrl+Enter or Meta+Enter saves
      if (e.key === 'Enter' && multiline && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        save();
      }
    },
    [cancel, save, multiline],
  );

  useEffect(
    () => () => {
      emitDirtyChange(false);
    },
    [emitDirtyChange],
  );

  // Not editable -- render plain text
  if (!canEdit) {
    return (
      <Tag className={className}>
        {value || placeholder}
      </Tag>
    );
  }

  // Editing mode
  if (editing) {
    const inputClasses = cn(
      'w-full bg-transparent border-b-2 border-primary outline-none',
      'px-1 -mx-1',
      className,
    );

    if (multiline) {
      return (
        <textarea
          ref={inputRef as React.RefObject<HTMLTextAreaElement>}
          value={draft}
          onChange={(e) => handleDraftChange(e.target.value)}
          onBlur={cancel}
          onKeyDown={handleKeyDown}
          className={cn(inputClasses, 'resize-none min-h-[3rem]')}
          rows={3}
          title="Ctrl+Enter to save, Escape to cancel"
        />
      );
    }

    return (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type="text"
        value={draft}
        onChange={(e) => handleDraftChange(e.target.value)}
        onBlur={save}
        onKeyDown={handleKeyDown}
        className={inputClasses}
      />
    );
  }

  // Display mode with hover indicator
  return (
    <Tag
      role="button"
      tabIndex={0}
      onClick={() => setEditing(true)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setEditing(true);
        }
      }}
      className={cn(
        'cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1 transition-colors duration-150',
        className,
      )}
    >
      {value || <span className="text-foreground/70 italic">{placeholder}</span>}
    </Tag>
  );
}
