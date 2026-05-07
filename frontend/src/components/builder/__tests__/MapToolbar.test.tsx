import { fireEvent, render, screen } from '@testing-library/react';
import { MapToolbar } from '../MapToolbar';
import { useWidgetStore } from '@/stores/map-widget-store';

const mockEnabledWidgets = vi.hoisted(() => ({
  value: null as string[] | null | undefined,
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledWidgets: () => ({ data: mockEnabledWidgets.value }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}));

describe('MapToolbar widget controls', () => {
  beforeEach(() => {
    mockEnabledWidgets.value = null;
    useWidgetStore.getState().replace([]);
  });

  it('renders available widget controls when unrestricted', () => {
    render(<MapToolbar />);

    expect(screen.getByRole('button', { name: 'Pan' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Measure' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Legend' })).toBeInTheDocument();
  });

  it('hides widget controls disabled by admin settings', () => {
    mockEnabledWidgets.value = [];
    render(<MapToolbar />);

    expect(screen.getByRole('button', { name: 'Pan' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Measure' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Legend' })).toBeNull();
  });

  it('pan control clears stale measurement state', () => {
    mockEnabledWidgets.value = [];
    useWidgetStore.getState().open('measurement');
    render(<MapToolbar />);

    fireEvent.click(screen.getByRole('button', { name: 'Pan' }));

    expect(useWidgetStore.getState().activeWidgets.has('measurement')).toBe(false);
  });

  it('renders style JSON action when provided', () => {
    const onStyleJsonClick = vi.fn();
    render(<MapToolbar onStyleJsonClick={onStyleJsonClick} />);

    fireEvent.click(screen.getByRole('button', { name: 'Style JSON' }));

    expect(onStyleJsonClick).toHaveBeenCalled();
  });
});
