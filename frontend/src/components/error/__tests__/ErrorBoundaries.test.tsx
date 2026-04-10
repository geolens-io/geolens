import { render, screen, fireEvent } from '@/test/test-utils';
import { AppErrorBoundary } from '../AppErrorBoundary';
import { MapErrorBoundary } from '../MapErrorBoundary';
import { LazyLoadErrorBoundary } from '../LazyLoadErrorBoundary';
import { RouteErrorBoundary } from '../RouteErrorBoundary';

// Suppress React error boundary console.error noise in tests
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

function ThrowingChild({ error }: { error?: Error }): React.ReactElement {
  throw error ?? new Error('Test error');
}

// --- AppErrorBoundary ---

describe('AppErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <AppErrorBoundary>
        <div>Hello</div>
      </AppErrorBoundary>,
    );
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('shows fallback UI with reload button when child throws', () => {
    render(
      <AppErrorBoundary>
        <ThrowingChild />
      </AppErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText(/unexpected error/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument();
  });

  it('displays the error message', () => {
    render(
      <AppErrorBoundary>
        <ThrowingChild error={new Error('Specific failure')} />
      </AppErrorBoundary>,
    );
    expect(screen.getByText('Specific failure')).toBeInTheDocument();
  });
});

// --- MapErrorBoundary ---

describe('MapErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <MapErrorBoundary>
        <div>Map content</div>
      </MapErrorBoundary>,
    );
    expect(screen.getByText('Map content')).toBeInTheDocument();
  });

  it('shows map error fallback when child throws', () => {
    render(
      <MapErrorBoundary>
        <ThrowingChild />
      </MapErrorBoundary>,
    );
    expect(screen.getByText('Map failed to load')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload map/i })).toBeInTheDocument();
  });

  it('shows unsaved warning when hasUnsavedChanges is true', () => {
    render(
      <MapErrorBoundary hasUnsavedChanges>
        <ThrowingChild />
      </MapErrorBoundary>,
    );
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  });

  it('does not show unsaved warning when hasUnsavedChanges is false', () => {
    render(
      <MapErrorBoundary hasUnsavedChanges={false}>
        <ThrowingChild />
      </MapErrorBoundary>,
    );
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();
  });

  it('reset button triggers state reset attempt', () => {
    render(
      <MapErrorBoundary>
        <ThrowingChild />
      </MapErrorBoundary>,
    );

    expect(screen.getByText('Map failed to load')).toBeInTheDocument();
    const reloadBtn = screen.getByRole('button', { name: /reload map/i });
    // Click triggers setState({ hasError: false }) which attempts re-mount.
    // Since ThrowingChild always throws, it re-catches and shows fallback again.
    fireEvent.click(reloadBtn);
    expect(screen.getByText('Map failed to load')).toBeInTheDocument();
  });
});

// --- LazyLoadErrorBoundary ---

describe('LazyLoadErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <LazyLoadErrorBoundary>
        <div>Lazy content</div>
      </LazyLoadErrorBoundary>,
    );
    expect(screen.getByText('Lazy content')).toBeInTheDocument();
  });

  it('shows retry UI on non-chunk error', () => {
    render(
      <LazyLoadErrorBoundary>
        <ThrowingChild />
      </LazyLoadErrorBoundary>,
    );
    expect(screen.getByText('Failed to load')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});

// --- RouteErrorBoundary ---

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useRouteError: vi.fn(() => new Error('Route error')),
    useNavigate: vi.fn(() => vi.fn()),
  };
});

describe('RouteErrorBoundary', () => {
  it('renders error message from useRouteError', () => {
    render(<RouteErrorBoundary />);
    expect(screen.getByText('Page error')).toBeInTheDocument();
    expect(screen.getByText('Route error')).toBeInTheDocument();
  });

  it('renders go back and go home buttons', () => {
    render(<RouteErrorBoundary />);
    expect(screen.getByRole('button', { name: /go back/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /go to home/i })).toBeInTheDocument();
  });
});
