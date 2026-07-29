// fix(#834): ThemeProvider must survive storage-blocked contexts (Safari
// private-mode iframes, strict cookie settings) where any localStorage access
// throws — previously this crashed before React mounted (white screen on the
// embed surface).
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeProvider, useTheme } from '../theme-provider';

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
