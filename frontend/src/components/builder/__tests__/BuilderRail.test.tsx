import { useState } from 'react';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { BuilderRail, type RailPanel } from '../BuilderRail';
import * as availabilityModule from '@/hooks/use-ai-availability';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}));

vi.mock('@/components/builder/HistoryPanel', () => ({
  HistoryPanel: ({ mapId }: { mapId?: string }) => (
    <div data-testid="history-panel">{mapId}</div>
  ),
}));

vi.mock('@/components/builder/ChatPanel', () => ({
  ChatPanel: () => <div data-testid="chat-panel" />,
}));

vi.mock('@/components/builder/AnalysisPanel', () => ({
  AnalysisPanel: () => <div data-testid="analysis-panel-mock" />,
}));

vi.mock('@/hooks/use-ai-availability', async (importOriginal) => {
  const actual = await importOriginal<typeof availabilityModule>();
  return {
    ...actual,
    useAIAvailability: vi.fn(() => ({
      isLoading: false,
      isAIAvailable: false,
      reason: null,
      data: undefined,
    })),
  };
});

vi.mock('@/stores/auth-store', async () => {
  const { create } = await import('zustand');
  const store = create<{
    token: string | null;
    user: { roles: string[] } | null;
    isAdmin: () => boolean;
  }>((set, get) => ({
    token: null,
    user: null,
    isAdmin: () => get().user?.roles.includes('admin') ?? false,
    setState: set,
  }));
  return { useAuthStore: store };
});

// fix(#816): the Settings CTA gates on can('manage_settings') — the
// capability the /admin/settings route enforces — not the isAdmin flag.
const permMocks = vi.hoisted(() => ({ capabilities: new Set<string>() }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => permMocks.capabilities.has(capability),
  }),
}));

// fix(#817): the CTA gate goes through useSettingsAdmin, which composes
// usePermissions with useEdition — mock the edition side too.
const editionMocks = vi.hoisted(() => ({ isMultiTenant: false }));
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: 'community',
    features: [],
    isEnterprise: false,
    isMultiTenant: editionMocks.isMultiTenant,
    isLoading: false,
    isResolved: true,
  }),
}));

function RailHarness({ showRail = true, aiAvailable = true }: { showRail?: boolean; aiAvailable?: boolean }) {
  const [activePanel, setActivePanel] = useState<RailPanel>(null);
  return (
    <BuilderRail
      activePanel={activePanel}
      onPanelChange={setActivePanel}
      aiAvailable={aiAvailable}
      showRail={showRail}
      notes=""
      onNotesChange={vi.fn()}
      mapId="map-1"
      layers={[]}
      onMarkDirty={vi.fn()}
    />
  );
}

describe('BuilderRail', () => {
  it('opens and closes the history panel from the icon rail', () => {
    render(<RailHarness />);

    const historyButton = screen.getByRole('button', { name: 'History' });
    fireEvent.click(historyButton);

    expect(historyButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('history-panel')).toHaveTextContent('map-1');

    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));

    expect(screen.queryByTestId('history-panel')).toBeNull();
  });

  it('renders an active panel without the icon rail for mobile sheets', () => {
    const { container } = render(
      <BuilderRail
        activePanel="history"
        onPanelChange={vi.fn()}
        aiAvailable
        showRail={false}
        notes=""
        onNotesChange={vi.fn()}
        mapId="map-1"
        layers={[]}
      />,
    );

    expect(screen.queryByRole('button', { name: 'History' })).toBeNull();
    expect(screen.getByTestId('history-panel')).toBeInTheDocument();
    expect(container.querySelector('aside')?.className).toContain('h-full');
    expect(container.querySelector('aside')?.className).toContain('min-h-0');
  });

  it('marks the map dirty when notes change', () => {
    const onNotesChange = vi.fn();
    const onMarkDirty = vi.fn();

    render(
      <BuilderRail
        activePanel="notes"
        onPanelChange={vi.fn()}
        aiAvailable
        notes=""
        onNotesChange={onNotesChange}
        mapId="map-1"
        layers={[]}
        onMarkDirty={onMarkDirty}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New note' } });

    expect(onNotesChange).toHaveBeenCalledWith('New note');
    expect(onMarkDirty).toHaveBeenCalled();
  });

  it('opens an AI unavailable panel without mounting ChatPanel', () => {
    // Mock reason to env_disabled so the panel renders the structured disabled state
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    render(<RailHarness aiAvailable={false} />);

    const aiButton = screen.getByRole('button', { name: 'AI unavailable' });
    expect(aiButton).toHaveAttribute('data-unavailable', 'true');
    expect(aiButton).not.toBeDisabled();
    fireEvent.click(aiButton);

    expect(screen.getByRole('status')).toHaveTextContent('AI is disabled');
    expect(screen.queryByTestId('chat-panel')).toBeNull();

    vi.restoreAllMocks();
  });

  it('gives notes a flexible editor area in sheet mode', () => {
    const { container } = render(
      <BuilderRail
        activePanel="notes"
        onPanelChange={vi.fn()}
        aiAvailable
        showRail={false}
        notes=""
        onNotesChange={vi.fn()}
      />,
    );

    const panel = container.querySelector('aside');
    const textarea = screen.getByRole('textbox');

    expect(panel?.className).toContain('h-full');
    expect(panel?.className).toContain('min-h-0');
    expect(textarea.className).toContain('flex-1');
    expect(textarea.className).toContain('min-h-[18rem]');
  });
});

describe('fix(#783) — focus restoration on panel close', () => {
  it('returns focus to the rail button when the close button dismisses the panel', async () => {
    render(<RailHarness />);
    const historyButton = screen.getByRole('button', { name: 'History' });
    fireEvent.click(historyButton);

    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));

    expect(screen.queryByTestId('history-panel')).toBeNull();
    await waitFor(() => expect(historyButton).toHaveFocus());
  });

  it('returns focus to the rail button when Escape dismisses the panel', async () => {
    render(<RailHarness />);
    const notesButton = screen.getByRole('button', { name: 'Notes' });
    fireEvent.click(notesButton);

    const textarea = screen.getByRole('textbox');
    textarea.focus();
    fireEvent.keyDown(textarea, { key: 'Escape' });

    expect(screen.queryByRole('textbox')).toBeNull();
    await waitFor(() => expect(notesButton).toHaveFocus());
  });
});

describe('fix(#788 item 5) — named aside landmarks', () => {
  it('names the icon rail and the expanded panel', () => {
    render(<RailHarness />);
    expect(
      screen.getByRole('complementary', { name: 'Builder tools' }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    // The panel aside takes its accessible name from its own title.
    expect(
      screen.getByRole('complementary', { name: 'History' }),
    ).toBeInTheDocument();
  });
});

describe('MAP-22 — Notes presence indicator', () => {
  // The dot is decorative (aria-hidden); the state is exposed via the notes
  // BUTTON's conditional accessible name (aria-label replaces the subtree, so
  // a label on the span was never announced — and aria-label on a role-less
  // span is invalid ARIA).
  it('folds notes presence into the button accessible name and renders a decorative dot', () => {
    render(
      <BuilderRail
        activePanel={null}
        onPanelChange={vi.fn()}
        aiAvailable
        notes="Some content"
        onNotesChange={vi.fn()}
        mapId="map-1"
        layers={[]}
      />,
    );

    const notesButton = screen.getByRole('button', { name: 'Notes (map has notes)' });
    const dot = notesButton.querySelector('[aria-hidden="true"].bg-primary');
    expect(dot).not.toBeNull();
    expect(dot!.className).toContain('size-1.5');
    expect(dot!.className).toContain('rounded-full');
  });

  it('does NOT signal notes presence when notes is empty or whitespace', () => {
    const whitespaceVariants = ['', '   ', '\n', '\t\n  '];

    for (const notes of whitespaceVariants) {
      const { unmount } = render(
        <BuilderRail
          activePanel={null}
          onPanelChange={vi.fn()}
          aiAvailable
          notes={notes}
          onNotesChange={vi.fn()}
          mapId="map-1"
          layers={[]}
        />,
      );

      expect(screen.queryByRole('button', { name: 'Notes (map has notes)' })).toBeNull();
      expect(screen.getByRole('button', { name: 'Notes' })).toBeInTheDocument();
      unmount();
    }
  });

  it('MAP-22 negative control — dot does not render on History or AI buttons even when notes is non-empty', () => {
    render(
      <BuilderRail
        activePanel={null}
        onPanelChange={vi.fn()}
        aiAvailable
        notes="Some content"
        onNotesChange={vi.fn()}
        mapId="map-1"
        layers={[]}
      />,
    );

    const historyButton = screen.getByRole('button', { name: /history/i });
    expect(historyButton.querySelector('[aria-hidden="true"].bg-primary')).toBeNull();

    const aiButton = screen.getByRole('button', { name: /ask ai/i });
    expect(aiButton.querySelector('[aria-hidden="true"].bg-primary')).toBeNull();
  });
});

describe('BuilderRail — analysis layer-ownership gate (#793 review)', () => {
  function renderAnalysisRail(layersMapId: string | null) {
    return render(
      <BuilderRail
        activePanel="analysis"
        onPanelChange={vi.fn()}
        aiAvailable={false}
        notes=""
        onNotesChange={vi.fn()}
        mapId="map-1"
        layers={[]}
        layersMapId={layersMapId}
        onMarkDirty={vi.fn()}
      />,
    );
  }

  it('holds the panel while layers still belong to the previous map', () => {
    renderAnalysisRail('previous-map');
    // Mounting now would judge this map's remembered form against the other
    // map's rows and overwrite it with fallbacks.
    expect(screen.queryByTestId('analysis-panel-mock')).not.toBeInTheDocument();
  });

  it('mounts the panel once the layers belong to this map', async () => {
    renderAnalysisRail('map-1');
    expect(await screen.findByTestId('analysis-panel-mock')).toBeInTheDocument();
  });
});

describe('BuilderRail — disabled-state taxonomy (Phase 1135 AI-02)', () => {
  beforeEach(() => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: null,
      data: undefined,
      status: 'success',
    } as never);
    useAuthStore.setState({ token: null, user: null });
    permMocks.capabilities = new Set();
    editionMocks.isMultiTenant = false;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders 'AI is disabled' + 'Go to Settings' CTA when reason='env_disabled' and caller holds manage_settings", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false, configured: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    permMocks.capabilities = new Set(['manage_settings']);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /go to settings/i });
    // fix(#816): the ?tab=ai form bounced to the General tab via the bare-path redirect.
    expect(cta).toHaveAttribute('href', '/admin/settings/ai');
  });

  it("renders 'AI is disabled' but NO CTA without manage_settings (even for the admin role flag)", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /go to settings/i })).not.toBeInTheDocument();
  });

  // fix(#817): in multi-tenant mode the /admin/settings route (and the
  // settings API behind it) requires manage_tenants, not manage_settings —
  // the CTA must follow the same mode-aware gate.
  it('multi-tenant: NO CTA for a manage_settings-only per-tenant admin', () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    editionMocks.isMultiTenant = true;
    permMocks.capabilities = new Set(['manage_settings']);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /go to settings/i })).not.toBeInTheDocument();
  });

  it('multi-tenant: shows the CTA for manage_tenants', () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    editionMocks.isMultiTenant = true;
    permMocks.capabilities = new Set(['manage_tenants']);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByRole('link', { name: /go to settings/i })).toHaveAttribute('href', '/admin/settings/ai');
  });

  it("renders 'AI not configured' + 'Configure in Settings' CTA when reason='no_key' and caller holds manage_settings", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: 'no_key',
    } as never);
    permMocks.capabilities = new Set(['manage_settings']);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI not configured/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /configure in settings/i })).toBeInTheDocument();
  });

  it("renders 'AI unavailable' + NO CTA when reason='permission' regardless of capabilities", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: 'permission',
    } as never);
    permMocks.capabilities = new Set(['manage_settings']);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    // The status container has the 'AI unavailable' title; use data-ai-reason to scope
    const statusEl = document.querySelector('[data-ai-reason="permission"]');
    expect(statusEl).toBeTruthy();
    expect(statusEl?.textContent).toMatch(/AI unavailable/i);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it("renders a spinner when isLoading is true (reason=null)", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: true,
      isAIAvailable: false,
      reason: null,
    } as never);
    const { container } = render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(container.querySelector('[role="status"] svg.animate-spin')).toBeTruthy();
  });
});
