import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@/test/test-utils';
import { ReportProblemHost } from '../ReportProblemHost';
import { useAuthStore } from '@/stores/auth-store';
import { clearReportEntries, pushReportEntry, useReportDialog } from '@/lib/report';

function signIn() {
  useAuthStore.setState({ token: 'tok', refreshToken: 'r', expiresAt: Date.now() + 1_000_000, user: null });
}

beforeEach(() => {
  clearReportEntries();
  useReportDialog.setState({ open: false });
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
});

describe('ReportProblemHost', () => {
  it('shows no floating button for an anonymous visitor with no errors', () => {
    render(<ReportProblemHost />);
    expect(screen.queryByRole('button', { name: /report a problem/i })).toBeNull();
  });

  it('surfaces the floating button to an anonymous visitor once an error is captured', async () => {
    render(<ReportProblemHost />);
    pushReportEntry({ severity: 'error', source: 'console', message: 'anon-visible failure' });
    expect(await screen.findByRole('button', { name: /report a problem/i })).toBeInTheDocument();
  });

  it('shows no floating button when authenticated and idle (no errors)', () => {
    signIn();
    render(<ReportProblemHost />);
    expect(screen.queryByRole('button', { name: /report a problem/i })).toBeNull();
  });

  it('shows the floating button with a count badge once errors are captured', async () => {
    signIn();
    render(<ReportProblemHost />);
    pushReportEntry({ severity: 'error', source: 'console', message: 'boom' });
    expect(await screen.findByRole('button', { name: /report a problem/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  // fix(#908): the badge counts distinct failures. An unrecovered tile error
  // writes both a `maplibre` row (which carries the sourceId) and a `console`
  // row from logUnhandledMapError, and it used to read "2" for one failure.
  it('counts one failure for the maplibre + console pair a 5xx tile writes', async () => {
    signIn();
    render(<ReportProblemHost />);
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Internal Server Error (500)',
      detail: 'source: dataset-abc',
    });
    pushReportEntry({
      severity: 'error',
      source: 'console',
      message: 'AJAXError: Internal Server Error (500)',
    });

    const button = await screen.findByRole('button', { name: /report a problem/i });
    expect(button).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('opens the wizard from the floating button', async () => {
    signIn();
    render(<ReportProblemHost />);
    pushReportEntry({ severity: 'error', source: 'console', message: 'boom' });
    fireEvent.click(await screen.findByRole('button', { name: /report a problem/i }));
    expect(await screen.findByText('What happened?')).toBeInTheDocument();
  });

  it('opens the wizard via the shared store (user-menu entry point) with no errors', async () => {
    signIn();
    render(<ReportProblemHost />);
    useReportDialog.getState().openReport();
    expect(await screen.findByText('What happened?')).toBeInTheDocument();
  });
});
