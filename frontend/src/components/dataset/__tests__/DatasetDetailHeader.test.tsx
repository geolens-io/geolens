import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Pencil, PenLine, Trash2 } from 'lucide-react';
import { useIsMobile } from '@/hooks/use-mobile';
import {
  DatasetDetailHeader,
  partitionActions,
  type DatasetDetailHeaderAction,
} from '../DatasetDetailHeader';

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: vi.fn(),
}));

const mockUseIsMobile = vi.mocked(useIsMobile);

function createAction(
  id: string,
  priority: number,
  onSelect: () => void,
  options: Partial<DatasetDetailHeaderAction> = {},
): DatasetDetailHeaderAction {
  const iconById = {
    edit: Pencil,
    draw: PenLine,
    delete: Trash2,
  } as const;

  return {
    id,
    label: id.toUpperCase(),
    icon: iconById[id as keyof typeof iconById] ?? Pencil,
    onSelect,
    priority,
    visible: true,
    ...options,
  };
}

describe('DatasetDetailHeader', () => {
  beforeEach(() => {
    mockUseIsMobile.mockReturnValue(false);
  });

  it('renders exactly one h1 for the dataset title', () => {
    render(
      <DatasetDetailHeader
        title="World Countries"
        onTitleSave={vi.fn().mockResolvedValue(undefined)}
        canEditTitle
      />,
    );

    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent('World Countries');
  });

  it('partitions actions deterministically for desktop and mobile budgets', () => {
    const actions = [
      createAction('draw', 2, vi.fn()),
      createAction('edit', 1, vi.fn()),
      createAction('delete', 3, vi.fn()),
      createAction('hidden', 0, vi.fn(), { visible: false }),
      createAction('secondary-edit', 1, vi.fn()),
    ];

    const desktop = partitionActions(actions, false);
    expect(desktop.primary.map((action) => action.id)).toEqual([
      'edit',
    ]);
    expect(desktop.overflow.map((action) => action.id)).toEqual([
      'secondary-edit',
      'draw',
      'delete',
    ]);

    const mobile = partitionActions(actions, true);
    expect(mobile.primary.map((action) => action.id)).toEqual([]);
    expect(mobile.overflow.map((action) => action.id)).toEqual([
      'edit',
      'secondary-edit',
      'draw',
      'delete',
    ]);
  });

  it('renders leadingContent inside the action area alongside action buttons', () => {
    const actions = [createAction('edit', 1, vi.fn())];
    render(
      <DatasetDetailHeader
        title="Test Dataset"
        actions={actions}
        leadingContent={<span data-testid="leading">Custom</span>}
      />,
    );

    expect(screen.getByTestId('leading')).toBeInTheDocument();
    expect(screen.getByTestId('leading')).toHaveTextContent('Custom');
  });

  it('renders leadingContent even without action buttons', () => {
    render(
      <DatasetDetailHeader
        title="Test Dataset"
        leadingContent={<span data-testid="leading">Solo</span>}
      />,
    );

    expect(screen.getByTestId('leading')).toBeInTheDocument();
  });

  it('keeps desktop primary actions visible and preserves disabled overflow state', async () => {
    const user = userEvent.setup();
    const editHandler = vi.fn();
    const drawHandler = vi.fn();
    const deleteHandler = vi.fn();

    render(
      <DatasetDetailHeader
        title="World Countries"
        actions={[
          createAction('edit', 1, editHandler),
          createAction('draw', 2, drawHandler),
          createAction('delete', 3, deleteHandler, { disabled: true }),
        ]}
      />,
    );

    // With DESKTOP_PRIMARY_ACTION_LIMIT=1, only EDIT is primary
    expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /more actions/i }));

    // DRAW and DELETE are in overflow
    const overflowDraw = screen.getByRole('menuitem', { name: 'DRAW' });
    expect(overflowDraw).toBeInTheDocument();

    const overflowDelete = screen.getByRole('menuitem', { name: 'DELETE' });
    expect(overflowDelete).toHaveAttribute('data-disabled', '');

    await user.click(overflowDelete);
    expect(deleteHandler).not.toHaveBeenCalled();
    expect(editHandler).not.toHaveBeenCalled();
    expect(drawHandler).not.toHaveBeenCalled();
  });

  it('h1 has break-words class for long titles', () => {
    render(<DatasetDetailHeader title="Test" />);

    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveClass('break-words');
  });

  it('mobile layout stacks title and actions vertically', () => {
    mockUseIsMobile.mockReturnValue(true);

    const actions = [createAction('edit', 1, vi.fn())];
    render(
      <DatasetDetailHeader
        title="Test Dataset"
        actions={actions}
        leadingContent={<span data-testid="leading">Button</span>}
      />,
    );

    const h1 = screen.getByRole('heading', { level: 1 });
    // The container wrapping both title area and action area
    const container = h1.closest('.min-w-0')!.parentElement!;
    expect(container).toHaveClass('flex-col');
  });

  it('action column allows wrapping on mobile', () => {
    mockUseIsMobile.mockReturnValue(true);

    render(
      <DatasetDetailHeader
        title="Test Dataset"
        leadingContent={<span data-testid="leading">Button</span>}
      />,
    );

    const leading = screen.getByTestId('leading');
    const actionContainer = leading.parentElement!;
    expect(actionContainer).not.toHaveClass('flex-shrink-0');
    expect(actionContainer).toHaveClass('flex-wrap');
  });

  it('overflow trigger renders with visible More label and aria-label', async () => {
    render(
      <DatasetDetailHeader
        title="Test Dataset"
        actions={[
          createAction('edit', 1, vi.fn()),
          createAction('delete', 2, vi.fn()),
        ]}
      />,
    );

    // edit is primary (priority 1), delete goes to overflow
    // The trigger must be queryable by aria-label "More actions"
    const trigger = screen.getByRole('button', { name: /more actions/i });
    expect(trigger).toBeInTheDocument();

    // The trigger must also have visible text "More" (desktop label)
    expect(trigger).toHaveTextContent('More');
  });

  it('overflow menu items carry tooltip title attributes', async () => {
    const user = userEvent.setup();

    render(
      <DatasetDetailHeader
        title="Test Dataset"
        actions={[
          createAction('edit', 1, vi.fn()),
          createAction('delete', 3, vi.fn(), {
            tooltip: 'Delete this dataset',
          }),
          createAction('draw', 2, vi.fn(), {
            tooltip: 'Draw on this dataset',
          }),
        ]}
      />,
    );

    // Open the overflow menu
    await user.click(screen.getByRole('button', { name: /more actions/i }));

    // Overflow items must carry title attributes so audit-style DOM snapshots
    // surface the action even without expanding the menu.
    const deleteItem = screen.getByRole('menuitem', { name: 'DELETE' });
    expect(deleteItem).toHaveAttribute('title', 'Delete this dataset');

    const drawItem = screen.getByRole('menuitem', { name: 'DRAW' });
    expect(drawItem).toHaveAttribute('title', 'Draw on this dataset');
  });
});
