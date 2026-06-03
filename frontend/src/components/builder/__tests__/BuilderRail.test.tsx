import { useState } from 'react';
import { fireEvent, screen, within } from '@testing-library/react';
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

describe('MAP-22 — Notes presence indicator', () => {
  it('renders presence dot when notes is non-empty', () => {
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

    const notesButton = screen.getByRole('button', { name: /notes/i });
    const dot = within(notesButton).getByLabelText('Map has notes');
    expect(dot).toBeInTheDocument();
    expect(dot.className).toContain('size-1.5');
    expect(dot.className).toContain('rounded-full');
    expect(dot.className).toContain('bg-primary');
  });

  it('does NOT render presence dot when notes is empty or whitespace', () => {
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

      expect(screen.queryByLabelText('Map has notes')).toBeNull();
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
    expect(within(historyButton).queryByLabelText('Map has notes')).toBeNull();

    const aiButton = screen.getByRole('button', { name: /ask ai/i });
    expect(within(aiButton).queryByLabelText('Map has notes')).toBeNull();
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
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders 'AI is disabled' + 'Go to Settings' CTA when reason='env_disabled' and isAdmin", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false, configured: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to settings/i })).toBeInTheDocument();
  });

  it("renders 'AI is disabled' but NO CTA when reason='env_disabled' and NOT isAdmin", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      data: { enabled: false } as never,
      isLoading: false,
      isAIAvailable: false,
      reason: 'env_disabled',
    } as never);
    useAuthStore.setState({ token: 't', user: { roles: ['member'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /go to settings/i })).not.toBeInTheDocument();
  });

  it("renders 'AI not configured' + 'Configure in Settings' CTA when reason='no_key' and isAdmin", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: 'no_key',
    } as never);
    useAuthStore.setState({ token: 't', user: { roles: ['admin'] } } as never);
    render(<BuilderRail activePanel="ai" onPanelChange={vi.fn()} aiAvailable={false} notes="" onNotesChange={vi.fn()} />);
    expect(screen.getByText(/AI not configured/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /configure in settings/i })).toBeInTheDocument();
  });

  it("renders 'AI unavailable' + NO CTA when reason='permission' regardless of isAdmin", () => {
    vi.spyOn(availabilityModule, 'useAIAvailability').mockReturnValue({
      isLoading: false,
      isAIAvailable: false,
      reason: 'permission',
    } as never);
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
