import { fireEvent, render, screen } from '@testing-library/react';
import { MapToolbar } from '../MapToolbar';
import { usePluginStore } from '@/stores/map-plugin-store';

const mockEnabledPlugins = vi.hoisted(() => ({
  value: null as string[] | null | undefined,
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: mockEnabledPlugins.value }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}));

describe('MapToolbar plugin controls', () => {
  beforeEach(() => {
    mockEnabledPlugins.value = null;
    usePluginStore.getState().replace([]);
  });

  it('renders available plugin controls when unrestricted', () => {
    render(<MapToolbar />);

    expect(screen.getByRole('button', { name: 'Pan' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Measure' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Legend' })).toBeInTheDocument();
  });

  it('hides plugin controls disabled by admin settings', () => {
    mockEnabledPlugins.value = [];
    render(<MapToolbar />);

    expect(screen.getByRole('button', { name: 'Pan' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Measure' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Legend' })).toBeNull();
  });

  it('pan control clears stale measurement state', () => {
    mockEnabledPlugins.value = [];
    usePluginStore.getState().open('measurement');
    render(<MapToolbar />);

    fireEvent.click(screen.getByRole('button', { name: 'Pan' }));

    expect(usePluginStore.getState().activePlugins.has('measurement')).toBe(false);
  });

  it('renders style JSON action when provided', () => {
    const onStyleJsonClick = vi.fn();
    render(<MapToolbar onStyleJsonClick={onStyleJsonClick} />);

    fireEvent.click(screen.getByRole('button', { name: 'Style JSON' }));

    expect(onStyleJsonClick).toHaveBeenCalled();
  });
});
