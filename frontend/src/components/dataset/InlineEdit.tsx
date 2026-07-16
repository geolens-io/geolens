import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
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
  /** fix(#458 E-04): emit an emptied value so the consumer can stage a clear.
   * Off by default — non-clearable fields (title) must never save empty. */
  allowClear?: boolean;
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
  allowClear = false,
}: InlineEditProps) {
  const { t } = useTranslation();
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
    try {
      if ((trimmed || allowClear) && trimmed !== value) {
        // BUG-040: wrap onSave in try/catch so a rejected mutation never
        // strands the editor open or produces an unhandled rejection.
        await onSave(trimmed);
      }
    } catch {
      toast.error(t('dataset:inline.saveFailed'));
    } finally {
      emitDirtyChange(false);
      setEditing(false);
    }
  }, [draft, value, allowClear, onSave, emitDirtyChange, t]);

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

  // fix(#458 E-32): clear the dirty flag on true unmount ONLY. Depending on
  // [emitDirtyChange] re-ran this cleanup whenever the onDirtyChange prop
  // identity changed — which the dirty change itself triggers when the parent
  // passes an inline arrow — instantly self-reverting the flag, so the
  // pending-edits bar never appeared for an in-progress multiline edit.
  const emitDirtyChangeRef = useRef(emitDirtyChange);
  useEffect(() => {
    emitDirtyChangeRef.current = emitDirtyChange;
  });
  useEffect(
    () => () => {
      emitDirtyChangeRef.current(false);
    },
    [],
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
        <div>
          <textarea
            ref={inputRef as React.RefObject<HTMLTextAreaElement>}
            value={draft}
            onChange={(e) => handleDraftChange(e.target.value)}
            onBlur={cancel}
            onKeyDown={handleKeyDown}
            // fix(#438): DS-03 — deliberately shares inputClasses with its
            // sibling <input> so the inline editor looks identical in both modes;
            // that's why it doesn't use the ui/textarea primitive.
            className={cn(inputClasses, 'resize-none min-h-[3rem]')}
            rows={3}
            title={t('common:inlineEdit.hint', { defaultValue: 'Ctrl+Enter to save, Escape to cancel' })}
          />
          {/* fix(#458 E-32): Ctrl+Enter was the ONLY save path, hinted solely
              by a hover tooltip — click-away cancels, so edits were silently
              lost. Visible buttons; mousedown is prevented so the textarea's
              blur→cancel doesn't fire before the click lands. */}
          <div className="mt-1 flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void save()}
            >
              {t('common:save')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onMouseDown={(e) => e.preventDefault()}
              onClick={cancel}
            >
              {t('common:cancel')}
            </Button>
          </div>
        </div>
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
        'cursor-pointer hover:bg-accent/50 rounded-sm px-1 -mx-1 transition-colors duration-150',
        className,
      )}
    >
      {value || <span className="text-muted-foreground italic">{placeholder}</span>}
    </Tag>
  );
}
