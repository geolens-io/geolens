import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import { TableHead } from '@/components/ui/table';

export type SortDirection = 'asc' | 'desc';

interface SortableColumnHeaderProps {
  /** Visible, already-localized column label. */
  label: string;
  /** Sort key sent to the API. Must be one the endpoint allowlists. */
  field: string;
  /** Currently active sort key across the whole table. */
  activeField: string;
  /** Direction of the active sort. Ignored unless `field === activeField`. */
  direction: SortDirection;
  /** Called with this column's field when the header is activated. */
  onSort: (field: string) => void;
  className?: string;
}

/**
 * A sortable `<th>` for the admin data tables.
 *
 * Shared on purpose: the admin surfaces (Users, Jobs, Audit, Shared Maps) all
 * render the same paginated-table shape, so the sort affordance and its
 * accessibility contract live in one place rather than per table.
 *
 * Accessibility notes:
 *  - the `<th>` carries `aria-sort`, which is where assistive tech reads sort
 *    STATE from; the button carries the ACTION.
 *  - the control is a real `<button>`, so it is keyboard-operable and
 *    focusable without any extra key handling.
 *  - the accessible name starts with the visible label and appends what
 *    activating will do ("Username, sort descending"), satisfying WCAG 2.5.3.
 *    The hint is a sibling text node rather than an aria-label because an
 *    aria-label would REPLACE the visible label instead of extending it.
 */
export function SortableColumnHeader({
  label,
  field,
  activeField,
  direction,
  onSort,
  className,
}: SortableColumnHeaderProps) {
  const { t } = useTranslation('admin');
  const isActive = field === activeField;
  // Activating an inactive column starts ascending; activating the active one
  // flips it. The hint always describes the NEXT state, not the current one.
  const nextDirection: SortDirection = isActive && direction === 'asc' ? 'desc' : 'asc';
  const hint =
    nextDirection === 'asc' ? t('sortable.sortAscending') : t('sortable.sortDescending');

  const SortIcon = !isActive ? ChevronsUpDown : direction === 'asc' ? ArrowUp : ArrowDown;

  return (
    <TableHead
      className={className}
      aria-sort={isActive ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {label}
        <span className="sr-only">, {hint}</span>
        <SortIcon
          aria-hidden="true"
          className={isActive ? 'h-3.5 w-3.5' : 'h-3.5 w-3.5 opacity-50'}
        />
      </button>
    </TableHead>
  );
}
