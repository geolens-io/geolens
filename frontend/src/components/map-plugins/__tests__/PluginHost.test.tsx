import type React from 'react';
import { render, screen } from '@testing-library/react';
import { LayoutGrid } from 'lucide-react';
import { usePluginStore } from '@/stores/map-plugin-store';
import { registerPlugin, getPlugins } from '../registry';
import { PluginHost, PluginSidebar, usePartitionedPlugins } from '../PluginHost';
import type { PluginContext } from '../types';

// Mock useEnabledPlugins — controls admin filtering
let mockEnabledPlugins: string[] | undefined = undefined;
vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: mockEnabledPlugins }),
}));

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const initialState = usePluginStore.getState();

// Register test plugins (additive, unique IDs)
const PLUGIN_A_ID = '_test-host-a';
const PLUGIN_B_ID = '_test-host-b';
const PLUGIN_CRASH_ID = '_test-host-crash';
const PLUGIN_SIDEBAR_ID = '_test-host-sidebar';

function PluginA({ ctx }: { ctx: PluginContext }) {
  return <div data-testid="plugin-a">A: {ctx.layers.length} layers</div>;
}

function PluginB({ ctx }: { ctx: PluginContext }) {
  return <div data-testid="plugin-b">B: {ctx.mapId}</div>;
}

function CrashingPlugin(): React.ReactElement {
  throw new Error('Widget crashed!');
}

function SidebarPlugin() {
  return <div data-testid="plugin-sidebar">Sidebar plugin</div>;
}

// Register once — registry is module-level
if (!getPlugins().find((w) => w.id === PLUGIN_A_ID)) {
  registerPlugin({ id: PLUGIN_A_ID, labelKey: 'widgets.a', icon: LayoutGrid, placement: { mode: 'floating', anchor: 'top-left' }, component: PluginA });
  registerPlugin({ id: PLUGIN_B_ID, labelKey: 'widgets.b', icon: LayoutGrid, placement: { mode: 'floating', anchor: 'top-right' }, component: PluginB });
  registerPlugin({ id: PLUGIN_CRASH_ID, labelKey: 'widgets.crash', icon: LayoutGrid, placement: { mode: 'floating', anchor: 'bottom-left' }, component: CrashingPlugin });
  registerPlugin({ id: PLUGIN_SIDEBAR_ID, labelKey: 'widgets.sidebar', icon: LayoutGrid, placement: { mode: 'sidebar' }, component: SidebarPlugin });
}

const testCtx: PluginContext = {
  mapInstance: null,
  layers: [],
  mapId: 'test-map-123',
};

/** Test wrapper that calls usePartitionedPlugins and passes byAnchor to PluginHost */
function TestPluginHost({ ctx }: { ctx: PluginContext }) {
  const { byAnchor } = usePartitionedPlugins();
  return <PluginHost byAnchor={byAnchor} ctx={ctx} />;
}

function TestPluginSidebar({ ctx }: { ctx: PluginContext }) {
  const { sidebar } = usePartitionedPlugins();
  return <PluginSidebar plugins={sidebar} ctx={ctx} />;
}

describe('PluginHost', () => {
  beforeEach(() => {
    usePluginStore.setState(initialState, true);
    mockEnabledPlugins = undefined; // default: all enabled
  });

  it('renders no plugin content when no plugins are active', () => {
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.queryByTestId('plugin-a')).toBeNull();
    expect(screen.queryByTestId('plugin-b')).toBeNull();
  });

  it('renders active plugins', () => {
    usePluginStore.getState().open(PLUGIN_A_ID);
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.getByTestId('plugin-a')).toHaveTextContent('A: 0 layers');
  });

  it('passes context to plugins', () => {
    usePluginStore.getState().open(PLUGIN_B_ID);
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.getByTestId('plugin-b')).toHaveTextContent('B: test-map-123');
  });

  // --- Admin filtering ---

  it('shows all active plugins when enabledPluginIds is null (default)', () => {
    mockEnabledPlugins = undefined;
    usePluginStore.getState().open(PLUGIN_A_ID);
    usePluginStore.getState().open(PLUGIN_B_ID);
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.getByTestId('plugin-a')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-b')).toBeInTheDocument();
  });

  it('filters out admin-disabled plugins', () => {
    mockEnabledPlugins = [PLUGIN_A_ID]; // only A enabled
    usePluginStore.getState().open(PLUGIN_A_ID);
    usePluginStore.getState().open(PLUGIN_B_ID);
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.getByTestId('plugin-a')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-b')).toBeNull();
  });

  it('renders no plugin content when admin disables all plugins', () => {
    mockEnabledPlugins = []; // none enabled
    usePluginStore.getState().open(PLUGIN_A_ID);
    render(<TestPluginHost ctx={testCtx} />);
    expect(screen.queryByTestId('plugin-a')).toBeNull();
  });

  it('partitions sidebar plugins for sidebar rendering', () => {
    usePluginStore.getState().open(PLUGIN_SIDEBAR_ID);
    render(<TestPluginSidebar ctx={testCtx} />);
    expect(screen.getByTestId('plugin-sidebar')).toBeInTheDocument();
  });

  // --- Error boundary ---

  it('isolates crashing plugins without affecting siblings', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    usePluginStore.getState().open(PLUGIN_A_ID);
    usePluginStore.getState().open(PLUGIN_CRASH_ID);
    render(<TestPluginHost ctx={testCtx} />);

    // Healthy plugin still renders
    expect(screen.getByTestId('plugin-a')).toBeInTheDocument();
    // Crashing plugin shows fallback (i18n value is renamed in Phase 1163, not here)
    expect(screen.getByText('This widget encountered an error')).toBeInTheDocument();
    // Error logged with plugin ID
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining(PLUGIN_CRASH_ID),
      expect.any(Error),
      expect.anything(),
    );
    spy.mockRestore();
  });
});
