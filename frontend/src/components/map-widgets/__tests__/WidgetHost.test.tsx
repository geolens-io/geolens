import { render, screen } from '@testing-library/react';
import { LayoutGrid } from 'lucide-react';
import { useWidgetStore } from '@/stores/map-widget-store';
import { registerWidget, getWidgets } from '../registry';
import { WidgetHost } from '../WidgetHost';
import type { WidgetContext } from '../types';

// Mock useEnabledWidgets — controls admin filtering
let mockEnabledWidgets: string[] | undefined = undefined;
vi.mock('@/hooks/use-settings', () => ({
  useEnabledWidgets: () => ({ data: mockEnabledWidgets }),
}));

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const initialState = useWidgetStore.getState();

// Register test widgets (additive, unique IDs)
const WIDGET_A_ID = '_test-host-a';
const WIDGET_B_ID = '_test-host-b';
const WIDGET_CRASH_ID = '_test-host-crash';

function WidgetA({ ctx }: { ctx: WidgetContext }) {
  return <div data-testid="widget-a">A: {ctx.layers.length} layers</div>;
}

function WidgetB({ ctx }: { ctx: WidgetContext }) {
  return <div data-testid="widget-b">B: {ctx.mapId}</div>;
}

function CrashingWidget(): JSX.Element {
  throw new Error('Widget crashed!');
}

// Register once — registry is module-level
if (!getWidgets().find((w) => w.id === WIDGET_A_ID)) {
  registerWidget({ id: WIDGET_A_ID, labelKey: 'widgets.a', icon: LayoutGrid, slot: 'top-left', component: WidgetA });
  registerWidget({ id: WIDGET_B_ID, labelKey: 'widgets.b', icon: LayoutGrid, slot: 'top-right', component: WidgetB });
  registerWidget({ id: WIDGET_CRASH_ID, labelKey: 'widgets.crash', icon: LayoutGrid, slot: 'bottom-left', component: CrashingWidget });
}

const testCtx: WidgetContext = {
  mapInstance: null,
  layers: [],
  mapId: 'test-map-123',
};

describe('WidgetHost', () => {
  beforeEach(() => {
    useWidgetStore.setState(initialState, true);
    mockEnabledWidgets = undefined; // default: all enabled
  });

  it('renders nothing when no widgets are active', () => {
    const { container } = render(<WidgetHost ctx={testCtx} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders active widgets', () => {
    useWidgetStore.getState().open(WIDGET_A_ID);
    render(<WidgetHost ctx={testCtx} />);
    expect(screen.getByTestId('widget-a')).toHaveTextContent('A: 0 layers');
  });

  it('passes context to widgets', () => {
    useWidgetStore.getState().open(WIDGET_B_ID);
    render(<WidgetHost ctx={testCtx} />);
    expect(screen.getByTestId('widget-b')).toHaveTextContent('B: test-map-123');
  });

  // --- Admin filtering ---

  it('shows all active widgets when enabledWidgetIds is null (default)', () => {
    mockEnabledWidgets = undefined;
    useWidgetStore.getState().open(WIDGET_A_ID);
    useWidgetStore.getState().open(WIDGET_B_ID);
    render(<WidgetHost ctx={testCtx} />);
    expect(screen.getByTestId('widget-a')).toBeInTheDocument();
    expect(screen.getByTestId('widget-b')).toBeInTheDocument();
  });

  it('filters out admin-disabled widgets', () => {
    mockEnabledWidgets = [WIDGET_A_ID]; // only A enabled
    useWidgetStore.getState().open(WIDGET_A_ID);
    useWidgetStore.getState().open(WIDGET_B_ID);
    render(<WidgetHost ctx={testCtx} />);
    expect(screen.getByTestId('widget-a')).toBeInTheDocument();
    expect(screen.queryByTestId('widget-b')).toBeNull();
  });

  it('renders nothing when admin disables all widgets', () => {
    mockEnabledWidgets = []; // none enabled
    useWidgetStore.getState().open(WIDGET_A_ID);
    const { container } = render(<WidgetHost ctx={testCtx} />);
    expect(container.innerHTML).toBe('');
  });

  // --- Error boundary ---

  it('isolates crashing widgets without affecting siblings', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    useWidgetStore.getState().open(WIDGET_A_ID);
    useWidgetStore.getState().open(WIDGET_CRASH_ID);
    render(<WidgetHost ctx={testCtx} />);

    // Healthy widget still renders
    expect(screen.getByTestId('widget-a')).toBeInTheDocument();
    // Crashing widget shows fallback
    expect(screen.getByText('This widget encountered an error')).toBeInTheDocument();
    // Error logged with widget ID
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining(WIDGET_CRASH_ID),
      expect.any(Error),
      expect.anything(),
    );
    spy.mockRestore();
  });
});
