import { useState, useRef, useEffect, useCallback, useId, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { MapLayerResponse } from '@/types/api';
import { MentionDropdown, type MentionItem } from './MentionDropdown';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  layers: MapLayerResponse[];
  disabled?: boolean;
  placeholder?: string;
  /** Fill the container height instead of auto-resizing to content. */
  grow?: boolean;
}

export interface TriggerState {
  type: '@' | '/';
  startIndex: number;
  query: string;
}

const SLASH_COMMAND_IDS = ['style', 'filter', 'label', 'query', 'add'] as const;

/**
 * Detect an active @-mention or /-command trigger ending at `cursorPos`.
 * Exported for unit testing (builder-audit #338 TEST-01): the cursor-sliced regex is
 * exactly the off-by-one-prone logic that previously had zero coverage.
 */
export function detectTrigger(value: string, cursorPos: number): TriggerState | null {
  const before = value.slice(0, cursorPos);

  // Check for @ trigger: not preceded by a word character
  const atMatch = before.match(/(^|[\s])@([^\s]*)$/);
  if (atMatch) {
    return {
      type: '@',
      startIndex: before.lastIndexOf('@'),
      query: atMatch[2],
    };
  }

  // Check for / trigger: at start or after whitespace
  const slashMatch = before.match(/(^|[\s])\/([^\s]*)$/);
  if (slashMatch) {
    return {
      type: '/',
      startIndex: before.lastIndexOf('/'),
      query: slashMatch[2],
    };
  }

  return null;
}

function filterItems(items: MentionItem[], query: string): MentionItem[] {
  const q = query.toLowerCase();
  return items.filter((item) => item.label.toLowerCase().includes(q));
}

/**
 * Compute the value + cursor position after inserting `item` for an active
 * trigger. Pure and exported for unit testing (builder-audit #338 TEST-01) — covers
 * bracket vs plain insertion and the +1-for-trigger-char offset arithmetic.
 *
 * `@`-mentions whose label contains a space use bracket syntax (`@[Layer Name] `);
 * otherwise a bare `@Name `. Slash commands always insert `<label> `.
 */
export function computeMentionInsertion(
  value: string,
  trigger: TriggerState,
  item: Pick<MentionItem, 'label'>,
): { value: string; cursor: number } {
  const before = value.slice(0, trigger.startIndex);
  const after = value.slice(
    trigger.startIndex + 1 + trigger.query.length, // +1 for trigger char
  );

  let insertion: string;
  if (trigger.type === '@') {
    insertion = item.label.includes(' ') ? `@[${item.label}] ` : `@${item.label} `;
  } else {
    insertion = `${item.label} `;
  }

  return { value: before + insertion + after, cursor: before.length + insertion.length };
}

export function ChatInput({
  value,
  onChange,
  onSubmit,
  layers,
  disabled = false,
  placeholder,
  grow = false,
}: ChatInputProps) {
  const { t } = useTranslation('builder');
  const [triggerState, setTriggerState] = useState<TriggerState | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listboxId = useId();

  // Build slash commands with i18n descriptions
  const slashCommands = useMemo<MentionItem[]>(() =>
    SLASH_COMMAND_IDS.map((id) => ({
      id,
      label: `/${id}`,
      description: t(`chat.commands.${id}`),
    })),
    [t],
  );

  // Build layer items for dropdown
  const layerItems = useMemo<MentionItem[]>(() =>
    layers.map((l) => ({
      id: l.id,
      label: l.display_name ?? l.dataset_name,
      description: l.dataset_geometry_type ?? undefined,
    })),
    [layers],
  );

  // Filtered items based on trigger
  const filteredItems = useMemo(() =>
    triggerState
      ? filterItems(triggerState.type === '@' ? layerItems : slashCommands, triggerState.query)
      : [],
    [triggerState, layerItems, slashCommands],
  );

  const dropdownOpen = triggerState !== null && filteredItems.length > 0;

  // Active option id for aria-activedescendant
  const activeOptionId = dropdownOpen ? `${listboxId}-option-${selectedIndex}` : undefined;

  // Reset selected index when query or items change
  useEffect(() => {
    setSelectedIndex(0);
  }, [triggerState?.query]);

  // Auto-resize textarea (skip in grow mode — textarea fills container)
  useEffect(() => {
    if (grow) return;
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, [value, grow]);

  const updateTrigger = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const cursor = el.selectionStart;
    setTriggerState(detectTrigger(value, cursor));
  }, [value]);

  // Update trigger on value change
  useEffect(() => {
    updateTrigger();
  }, [updateTrigger]);

  function selectItem(index: number) {
    if (!triggerState) return;
    const item = filteredItems[index];
    if (!item) return;

    const { value: newValue, cursor: newCursor } = computeMentionInsertion(value, triggerState, item);

    onChange(newValue);
    setTriggerState(null);

    // Set cursor position after React re-render
    requestAnimationFrame(() => {
      textareaRef.current?.setSelectionRange(newCursor, newCursor);
      textareaRef.current?.focus();
    });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (dropdownOpen) {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex((prev) => (prev + 1) % filteredItems.length);
          return;
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % filteredItems.length);
          return;
        case 'Tab':
        case 'Enter':
          e.preventDefault();
          selectItem(selectedIndex);
          return;
        case 'Escape':
          e.preventDefault();
          setTriggerState(null);
          return;
      }
    }

    // When dropdown is closed, Enter sends
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
  }

  function handleClick() {
    // Re-detect trigger on click (cursor may have moved)
    updateTrigger();
  }

  return (
    <div className={grow ? "relative flex-1 flex flex-col min-h-0" : "relative flex-1"}>
      {dropdownOpen && (
        <MentionDropdown
          id={listboxId}
          items={filteredItems}
          selectedIndex={selectedIndex}
          onSelect={selectItem}
          type={triggerState!.type}
          label={triggerState!.type === '@' ? t('chat.layersDropdown') : t('chat.commandsDropdown')}
        />
      )}
      {/* fix(#438): DS-03 — kept as a raw textarea, not the ui/textarea
          primitive: this one auto-resizes, is a combobox for @-mentions, and
          carries bespoke keyboard handling. */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={handleClick}
        placeholder={placeholder ?? t('chat.mentionHint')}
        disabled={disabled}
        rows={grow ? undefined : 1}
        role="combobox"
        aria-expanded={dropdownOpen}
        aria-controls={dropdownOpen ? listboxId : undefined}
        aria-activedescendant={activeOptionId}
        aria-autocomplete="list"
        aria-haspopup="listbox"
        className={
          grow
            ? "flex-1 min-h-0 w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
            : "flex w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
        }
        style={grow ? undefined : { minHeight: '2rem' }}
      />
    </div>
  );
}
