import { useEffect, useRef, type ReactNode } from 'react';
import { Table2, X } from 'lucide-react';
import type { TableShellSize } from '@/components/dataset/hooks/use-table-shell-size';

/** A square header control: 28px, 44px on coarse pointers. */
export const panelIconButtonClass =
  'flex h-7 w-7 pointer-coarse:size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export interface DockedPanelHeaderProps {
  /** Names the panel; rendered as the heading unless `picker` replaces it. */
  title: string;
  /** The heading's id, for the host's aria-labelledby. */
  titleId: string;
  /** Replaces the heading, e.g. a layer select carrying `titleId` on its selected option. */
  picker?: ReactNode;
  /** Controls between the icon and the name, e.g. a view switch. */
  leading?: ReactNode;
  count?: ReactNode;
  /** Controls before the Columns menu, e.g. an In view switch. */
  extras?: ReactNode;
  columns?: ReactNode;
  /** Controls between the Columns menu and close, e.g. an expand button. */
  trailing?: ReactNode;
  /** A status line under the controls. */
  notice?: ReactNode;
  onClose: () => void;
  closeLabel: string;
}

/**
 * One header row for a bottom-docked panel: name or picker, count, extras,
 * then Columns and close kept together at the end. The name truncates rather
 * than wrap the row, and a notice takes the one allowed second line.
 */
export function DockedPanelHeader({
  title,
  titleId,
  picker,
  leading,
  count,
  extras,
  columns,
  trailing,
  notice,
  onClose,
  closeLabel,
}: DockedPanelHeaderProps) {
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-0.5 border-b px-3 py-1">
      <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      {leading}
      {picker ?? (
        <h2 id={titleId} data-testid="attribute-table-drawer-title" className="min-w-0 flex-1 truncate text-sm">
          {title}
        </h2>
      )}
      {count && <span className="text-xs">{count}</span>}
      {notice && (
        <div className="order-last flex basis-full flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
          {notice}
        </div>
      )}
      <div className="ms-auto flex shrink-0 items-center gap-1">
        {extras}
        {columns}
        {trailing}
        <button type="button" onClick={onClose} aria-label={closeLabel} className={panelIconButtonClass}>
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

interface DockedPanelFrameProps {
  /** The resize handle's sizing and name; omitted, the frame has no handle. */
  resize?: { size: TableShellSize; label: string };
  children: ReactNode;
}

/** The resize separator above a docked panel's header and body. */
export function DockedPanelFrame({ resize, children }: DockedPanelFrameProps) {
  return (
    <>
      {/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- role="separator" with aria-orientation is the WAI-ARIA separator (resizable) pattern; the rules' default interactive lists lag it. */}
      {resize && (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label={resize.label}
          tabIndex={0}
          data-testid="attribute-table-drawer-resize"
          className="group/handle flex h-3 shrink-0 cursor-row-resize items-center justify-center touch-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          {...resize.size.separatorProps}
          onPointerCancel={resize.size.separatorProps.onPointerUp}
        >
          <span aria-hidden="true" className="h-1 w-10 rounded-full bg-muted-foreground/40 group-hover/handle:bg-muted-foreground/70" />
        </div>
      )}
      {/* eslint-enable jsx-a11y/no-noninteractive-tabindex */}
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </>
  );
}

/**
 * Focus for a control that a switch remounts (a layer picker, a view switch):
 * call `willSwitch` before switching, and the element behind `ref` takes focus
 * once `switchKey` changes. Mounting never moves focus.
 */
export function useRefocusAfterSwitch<T extends HTMLElement>(switchKey: unknown) {
  const ref = useRef<T | null>(null);
  const pendingRef = useRef(false);
  useEffect(() => {
    if (!pendingRef.current) return;
    pendingRef.current = false;
    ref.current?.focus();
  }, [switchKey]);
  return { ref, willSwitch: () => { pendingRef.current = true; } };
}

interface LayerPickerProps {
  label: string;
  /** Set on the selected option, so the picker names the panel once. */
  titleId: string;
  options: readonly { id: string; name: string }[];
  value: string;
  onChange: (id: string) => void;
  refocus: ReturnType<typeof useRefocusAfterSwitch<HTMLSelectElement>>;
}

/** The header's layer select; it keeps focus across the switch that remounts it. */
export function LayerPicker({ label, titleId, options, value, onChange, refocus }: LayerPickerProps) {
  return (
    <select
      ref={refocus.ref}
      aria-label={label}
      className="h-7 pointer-coarse:min-h-11 min-w-0 max-w-40 flex-1 truncate cursor-pointer rounded-md border bg-transparent px-1.5 text-xs"
      value={value}
      onChange={(e) => {
        refocus.willSwitch();
        onChange(e.target.value);
      }}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id} id={option.id === value ? titleId : undefined}>
          {option.name}
        </option>
      ))}
    </select>
  );
}
