import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { BuilderRail, type RailPanel } from '../BuilderRail';

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
    render(<RailHarness aiAvailable={false} />);

    const aiButton = screen.getByRole('button', { name: 'AI unavailable' });
    expect(aiButton).toHaveAttribute('data-unavailable', 'true');
    expect(aiButton).not.toBeDisabled();
    fireEvent.click(aiButton);

    expect(screen.getByRole('status')).toHaveTextContent('AI is unavailable');
    expect(screen.queryByTestId('chat-panel')).toBeNull();
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
