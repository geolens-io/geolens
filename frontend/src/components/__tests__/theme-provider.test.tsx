// ThemeProvider must survive storage-blocked contexts (Safari
// private-mode iframes, strict cookie settings) where any localStorage access
// throws, which would otherwise crash before React mounted (white screen on
// the embed surface).
import { act, render, screen, fireEvent } from '@testing-library/react';
import { ThemeProvider, useForcedTheme, useTheme } from '../theme-provider';

function ThemeConsumer() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setTheme('dark')}>go dark</button>
    </div>
  );
}

describe('ThemeProvider storage-blocked fallback', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders with the default theme when localStorage.getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: storage blocked');
    });

    render(
      <ThemeProvider defaultTheme="light">
        <ThemeConsumer />
      </ThemeProvider>,
    );

    expect(screen.getByTestId('theme')).toHaveTextContent('light');
  });

  it('setTheme still updates in-memory when localStorage.setItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: storage blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError: storage blocked');
    });

    render(
      <ThemeProvider defaultTheme="light">
        <ThemeConsumer />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'go dark' }));
    expect(screen.getByTestId('theme')).toHaveTextContent('dark');
  });

  it('reads the stored theme when storage is available', () => {
    localStorage.setItem('geolens-theme', 'dark');
    render(
      <ThemeProvider defaultTheme="light">
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('theme')).toHaveTextContent('dark');
    localStorage.removeItem('geolens-theme');
  });
});

describe('useForcedTheme', () => {
  let systemDark = false;
  const listeners = new Set<() => void>();

  function setSystem(dark: boolean) {
    systemDark = dark;
    listeners.forEach((listener) => listener());
  }

  beforeEach(() => {
    systemDark = false;
    listeners.clear();
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        get matches() {
          return systemDark;
        },
        addEventListener: (_: string, listener: () => void) => listeners.add(listener),
        removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
      })),
    );
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.classList.remove('light', 'dark');
  });

  function Page({ theme }: { theme: 'follow' | 'light' | 'dark' | null }) {
    useForcedTheme(theme);
    return null;
  }

  function Probe() {
    const { resolvedTheme, theme } = useTheme();
    return <span data-testid="probe">{`${theme}:${resolvedTheme}`}</span>;
  }

  const root = document.documentElement;

  function renderWith(page: React.ReactNode, defaultTheme: 'system' | 'light' | 'dark' = 'system') {
    return render(
      <ThemeProvider defaultTheme={defaultTheme}>
        <Probe />
        {page}
      </ThemeProvider>,
    );
  }

  it('shows dark to a reader whose system is light, then restores on unmount', () => {
    const view = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(root).toHaveClass('light');

    view.rerender(
      <ThemeProvider>
        <Probe />
        <Page theme="dark" />
      </ThemeProvider>,
    );
    expect(root).toHaveClass('dark');
    expect(root).not.toHaveClass('light');
    expect(screen.getByTestId('probe')).toHaveTextContent('system:dark');
    expect(localStorage.getItem('geolens-theme')).toBeNull();

    view.rerender(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(root).toHaveClass('light');
    expect(root).not.toHaveClass('dark');
  });

  it('ignores a system change while a theme is forced', () => {
    renderWith(<Page theme="light" />);
    act(() => setSystem(true));
    expect(root).toHaveClass('light');
    expect(root).not.toHaveClass('dark');
  });

  it('tracks the system setting when the page follows the reader', () => {
    renderWith(<Page theme="follow" />);
    expect(root).toHaveClass('light');
    act(() => setSystem(true));
    expect(root).toHaveClass('dark');
    expect(root).not.toHaveClass('light');
  });
});
