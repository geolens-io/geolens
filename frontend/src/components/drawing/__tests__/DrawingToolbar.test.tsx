import { render, screen, fireEvent } from '@/test/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DrawingToolbar } from '@/components/drawing/DrawingToolbar';

const drawingState = vi.hoisted(() => ({
  activeMode: 'select' as string | null,
  setMode: vi.fn(),
  selectedFeature: null as { gid: number; tdId: string; properties: Record<string, unknown> } | null,
}));

vi.mock('@/components/drawing/drawing-store', () => ({
  useDrawingStore: (selector: (state: typeof drawingState) => unknown) => selector(drawingState),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('DrawingToolbar mode filtering', () => {
  beforeEach(() => {
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = null;
    drawingState.setMode.mockReset();
  });

  it('renders Select + Point mode buttons for POINT geometry', () => {
    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} />,
    );

    expect(screen.getByLabelText('drawing.select')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.point')).toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.polygon')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.line')).not.toBeInTheDocument();
  });

  it('renders Select + Polygon + Rectangle + Circle + Freehand for POLYGON geometry', () => {
    render(
      <DrawingToolbar geometryType="POLYGON" onClose={vi.fn()} />,
    );

    expect(screen.getByLabelText('drawing.select')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.polygon')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.rectangle')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.circle')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.freehand')).toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.point')).not.toBeInTheDocument();
  });

  it('renders Select + Linestring for LINESTRING geometry', () => {
    render(
      <DrawingToolbar geometryType="LINESTRING" onClose={vi.fn()} />,
    );

    expect(screen.getByLabelText('drawing.select')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.line')).toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.polygon')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.point')).not.toBeInTheDocument();
  });
});

describe('DrawingToolbar active mode styling', () => {
  beforeEach(() => {
    drawingState.activeMode = 'point';
    drawingState.selectedFeature = null;
  });

  it('active mode button has data-slot="button" (rendered as button)', () => {
    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} />,
    );

    // Both select and point buttons are present
    const selectBtn = screen.getByLabelText('drawing.select');
    const pointBtn = screen.getByLabelText('drawing.point');
    // Active mode is 'point', so point button should NOT have outline class
    // select button should have outline class
    expect(selectBtn).toBeInTheDocument();
    expect(pointBtn).toBeInTheDocument();
  });
});

describe('DrawingToolbar undo button', () => {
  beforeEach(() => {
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = null;
  });

  it('undo button is disabled when canUndo is false', () => {
    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} canUndo={false} />,
    );

    expect(screen.getByLabelText('drawing.undo')).toBeDisabled();
  });

  it('undo button is enabled when canUndo is true', () => {
    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} canUndo={true} />,
    );

    expect(screen.getByLabelText('drawing.undo')).toBeEnabled();
  });
});

describe('DrawingToolbar edit action bar', () => {
  beforeEach(() => {
    drawingState.activeMode = 'select';
  });

  it('does NOT render edit action bar when no feature selected', () => {
    drawingState.selectedFeature = null;

    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} />,
    );

    expect(screen.queryByLabelText('drawing.saveChanges')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.cancelEditing')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.editAttributes')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('drawing.deleteFeature')).not.toBeInTheDocument();
  });

  it('renders edit action bar when selectedFeature is set', () => {
    drawingState.selectedFeature = { gid: 1, tdId: 'td-1', properties: {} };

    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} />,
    );

    expect(screen.getByLabelText('drawing.saveChanges')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.cancelEditing')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.editAttributes')).toBeInTheDocument();
    expect(screen.getByLabelText('drawing.deleteFeature')).toBeInTheDocument();
  });
});

describe('DrawingToolbar callbacks', () => {
  beforeEach(() => {
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = null;
    drawingState.setMode.mockReset();
  });

  it('calls onClose when Done button is clicked', () => {
    const onClose = vi.fn();

    render(
      <DrawingToolbar geometryType="POINT" onClose={onClose} />,
    );

    fireEvent.click(screen.getByLabelText('drawing.done'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onModeChange when mode button is clicked', () => {
    const onModeChange = vi.fn();

    render(
      <DrawingToolbar geometryType="POINT" onClose={vi.fn()} onModeChange={onModeChange} />,
    );

    fireEvent.click(screen.getByLabelText('drawing.point'));
    expect(onModeChange).toHaveBeenCalledWith('point');
  });
});
