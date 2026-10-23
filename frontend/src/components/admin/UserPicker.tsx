import { forwardRef, useEffect, useId, useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { cn } from '@/lib/utils';

export interface PickerUser {
  id: string;
  username: string;
}

interface UserPickerProps {
  label: string;
  users: PickerUser[];
  onSelect: (user: PickerUser) => void;
  disabled?: boolean;
  /** Reports whether the list is open, so an enclosing dialog can leave Escape to it. */
  onOpenChange?: (open: boolean) => void;
}

const MAX_OPTIONS = 50;

/**
 * Searchable user list following the ARIA combobox pattern: focus stays in the
 * input, arrow keys move the active option, Enter picks it and Escape closes
 * the list before it can close an enclosing dialog.
 */
export const UserPicker = forwardRef<HTMLInputElement, UserPickerProps>(function UserPicker(
  { label, users, onSelect, disabled, onOpenChange },
  ref,
) {
  const { t } = useTranslation('admin');
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const listId = `${baseId}-list`;
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const found = needle ? users.filter((u) => u.username.toLowerCase().includes(needle)) : users;
    return found.slice(0, MAX_OPTIONS);
  }, [users, query]);

  useEffect(() => onOpenChange?.(open), [open, onOpenChange]);

  const expanded = open && matches.length > 0;
  const activeIndex = Math.min(active, Math.max(matches.length - 1, 0));
  const optionId = (index: number) => `${baseId}-option-${index}`;

  function select(user: PickerUser) {
    onSelect(user);
    setQuery('');
    setActive(0);
    setOpen(false);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp':
        event.preventDefault();
        if (!open) setOpen(true);
        else if (matches.length > 0) {
          const step = event.key === 'ArrowDown' ? 1 : -1;
          setActive((activeIndex + step + matches.length) % matches.length);
        }
        break;
      case 'Enter':
        if (expanded) {
          event.preventDefault();
          select(matches[activeIndex]);
        }
        break;
      case 'Escape':
        if (open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
        }
        break;
    }
  }

  const status = !open
    ? ''
    : matches.length === 0
      ? t('groups.picker.noMatches')
      : t('groups.picker.results', { count: matches.length });

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId}>{label}</Label>
      <div className="relative">
        <Input
          ref={ref}
          id={inputId}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={expanded ? optionId(activeIndex) : undefined}
          autoComplete="off"
          value={query}
          disabled={disabled}
          placeholder={t('groups.picker.placeholder')}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => setOpen(false)}
        />
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          hidden={!expanded}
          className="absolute inset-x-0 top-full z-10 mt-1 max-h-48 overflow-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {matches.map((user, index) => (
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events -- the combobox input owns keyboard selection; options are never focused
            <li
              key={user.id}
              id={optionId(index)}
              role="option"
              aria-selected={index === activeIndex}
              // Keeps focus in the input so the click isn't preceded by a blur that closes the list.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => select(user)}
              className={cn(
                'cursor-pointer rounded-sm px-2 py-1.5 text-sm',
                index === activeIndex && 'bg-accent text-accent-foreground',
              )}
            >
              {user.username}
            </li>
          ))}
        </ul>
      </div>
      {open && matches.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('groups.picker.noMatches')}</p>
      )}
      <LiveAnnouncement text={status} delayMs={300} />
    </div>
  );
});
