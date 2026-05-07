import { fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { MapTitleBar, type OverflowActions } from '../MapTitleBar';

// i18n mock — same defaultValue-passthrough pattern used in
// MapToolbar.test.tsx and LayerPanel.test.tsx in this dir.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

function makeOverflow(overrides: Partial<OverflowActions> = {}): OverflowActions {
  return {
    onExportPNG: vi.fn(),
    onShowInfo: vi.fn(),
    onFork: vi.fn(),
    isForkPending: false,
    ...overrides,
  };
}

function defaultProps(
  overrides: Partial<React.ComponentProps<typeof MapTitleBar>> = {},
): React.ComponentProps<typeof MapTitleBar> {
  return {
    name: 'My Map',
    onNameChange: vi.fn(),
    onMarkDirty: vi.fn(),
    hasUnsavedChanges: false,
    isSaving: false,
    onSave: vi.fn(),
    overflow: makeOverflow(),
    ...overrides,
  };
}

describe('MapTitleBar', () => {
  it('typing into the name input fires onNameChange and onMarkDirty', () => {
    const onNameChange = vi.fn();
    const onMarkDirty = vi.fn();

    render(
      <MapTitleBar
        {...defaultProps({ name: 'My Map', onNameChange, onMarkDirty })}
      />,
    );

    // The map-name input has aria-label "Map name" (from t('mapNameLabel', { defaultValue: 'Map name' }))
    const input = screen.getByRole('textbox', { name: 'Map name' });
    fireEvent.change(input, { target: { value: 'New Name' } });

    expect(onNameChange).toHaveBeenCalledWith('New Name');
    expect(onMarkDirty).toHaveBeenCalledTimes(1);
  });

  it('description input renders only when onDescriptionChange is provided', () => {
    const { rerender } = render(
      <MapTitleBar {...defaultProps({ description: 'ignored without callback' })} />,
    );
    // Without the callback the description input is not rendered
    expect(screen.queryByRole('textbox', { name: 'Description' })).not.toBeInTheDocument();

    rerender(
      <MapTitleBar
        {...defaultProps({
          description: 'A nice map',
          onDescriptionChange: vi.fn(),
        })}
      />,
    );
    const desc = screen.getByRole('textbox', { name: 'Description' }) as HTMLInputElement;
    expect(desc).toBeInTheDocument();
    expect(desc.value).toBe('A nice map');
  });

  it('shows the unsaved-changes orange dot and "Save" label when hasUnsavedChanges=true', () => {
    render(
      <MapTitleBar
        {...defaultProps({ hasUnsavedChanges: true, isSaving: false })}
      />,
    );

    // The orange dot is identifiable by its aria-label
    expect(screen.getByLabelText('Unsaved changes')).toBeInTheDocument();
    // Save button shows the "Save" label (from t('actions.save', { defaultValue: 'Save' }))
    // The button itself uses the longer aria-label "Save (Cmd/Ctrl+S)" so query by text.
    expect(screen.getByText('Save')).toBeInTheDocument();
  });

  it('shows the all-saved indicator and "Saved" label when hasUnsavedChanges=false', () => {
    render(
      <MapTitleBar
        {...defaultProps({ hasUnsavedChanges: false, isSaving: false })}
      />,
    );

    // No "Unsaved changes" indicator
    expect(screen.queryByLabelText('Unsaved changes')).not.toBeInTheDocument();
    // Save button shows "Saved"
    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  it('disables the save button and shows a spinner when isSaving=true', () => {
    const { container } = render(
      <MapTitleBar
        {...defaultProps({ hasUnsavedChanges: true, isSaving: true })}
      />,
    );

    // Save button is disabled while saving (query by aria-label so we don't
    // accidentally match the Share/More-actions buttons).
    const saveBtn = screen.getByRole('button', { name: /^Save \(/ });
    expect(saveBtn).toBeDisabled();
    // Loader2 from lucide-react renders an SVG with class "animate-spin"
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).not.toBeNull();
  });

  it('clicking the save button fires onSave', () => {
    const onSave = vi.fn();
    render(
      <MapTitleBar
        {...defaultProps({ hasUnsavedChanges: true, isSaving: false, onSave })}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /^Save \(/ }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('renders the Share button only when onShare is provided and forwards clicks', () => {
    const { rerender } = render(<MapTitleBar {...defaultProps()} />);
    // Without onShare → no Share button
    expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument();

    const onShare = vi.fn();
    rerender(<MapTitleBar {...defaultProps({ onShare })} />);

    const shareBtn = screen.getByRole('button', { name: 'Share' });
    expect(shareBtn).toBeInTheDocument();
    fireEvent.click(shareBtn);
    expect(onShare).toHaveBeenCalledTimes(1);
  });

  it('overflow dropdown exposes Download PNG / Map info / Duplicate map and disables Duplicate when isForkPending', async () => {
    // Radix DropdownMenu requires userEvent (full pointer-event simulation)
    // — fireEvent.click on the trigger leaves data-state="closed" and the
    // portal never renders. Match the DatasetDetailHeader.test.tsx pattern.
    const user = userEvent.setup();
    const onExportPNG = vi.fn();
    const onShowInfo = vi.fn();
    const onFork = vi.fn();
    const overflow = makeOverflow({
      onExportPNG,
      onShowInfo,
      onFork,
      isForkPending: true,
    });

    render(<MapTitleBar {...defaultProps({ overflow })} />);

    // Open the dropdown
    await user.click(screen.getByRole('button', { name: 'More actions' }));

    const downloadItem = await screen.findByRole('menuitem', { name: /Download PNG/i });
    const infoItem = screen.getByRole('menuitem', { name: /Map info/i });
    const forkItem = screen.getByRole('menuitem', { name: /Duplicate map/i });

    expect(downloadItem).toBeInTheDocument();
    expect(infoItem).toBeInTheDocument();
    // Duplicate map is marked disabled when isForkPending=true (Radix sets
    // data-disabled="" + aria-disabled="true"). This is the contract — the
    // visible/programmatic disabled state. (Radix DropdownMenuItem does
    // forward onClick on mouse-clicks even when data-disabled is set, so the
    // disabled gate is enforced via the data-/aria- attributes that drive
    // styling and assistive-tech announcements, not by suppressing onClick.)
    expect(forkItem).toHaveAttribute('data-disabled');
    expect(forkItem).toHaveAttribute('aria-disabled', 'true');

    // Click an active item — Radix closes the menu afterwards.
    await user.click(downloadItem);
    expect(onExportPNG).toHaveBeenCalledTimes(1);

    // Reopen the menu and click Map info
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    const infoAgain = await screen.findByRole('menuitem', { name: /Map info/i });
    await user.click(infoAgain);
    expect(onShowInfo).toHaveBeenCalledTimes(1);
  });

  it('Duplicate map menuitem is enabled and clickable when isForkPending=false', async () => {
    const user = userEvent.setup();
    const onFork = vi.fn();
    const overflow = makeOverflow({ onFork, isForkPending: false });

    render(<MapTitleBar {...defaultProps({ overflow })} />);

    await user.click(screen.getByRole('button', { name: 'More actions' }));
    const forkItem = await screen.findByRole('menuitem', { name: /Duplicate map/i });
    // Sanity: not disabled when isForkPending=false
    expect(forkItem).not.toHaveAttribute('data-disabled');

    // within() narrows queries to the menuitem subtree (defensive against
    // portal-rendering quirks in different Radix versions).
    within(forkItem).getByText(/Duplicate map/i);

    await user.click(forkItem);
    expect(onFork).toHaveBeenCalledTimes(1);
  });
});
