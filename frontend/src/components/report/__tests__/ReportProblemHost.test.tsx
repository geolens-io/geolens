import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@/test/test-utils';
import { ReportProblemHost } from '../ReportProblemHost';
import { useAuthStore } from '@/stores/auth-store';
import { clearReportEntries, pushReportEntry } from '@/lib/report';

function signIn() {
  useAuthStore.setState({ token: 'tok', refreshToken: 'r', expiresAt: Date.now() + 1_000_000, user: null });
}

beforeEach(() => {
  clearReportEntries();
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
});

describe('ReportProblemHost', () => {
  it('renders nothing for unauthenticated users', () => {
    render(<ReportProblemHost />);
    expect(screen.queryByRole('button', { name: 'Report a problem' })).toBeNull();
  });

  it('shows a quiet report button when authenticated', () => {
    signIn();
    render(<ReportProblemHost />);
    expect(screen.getByRole('button', { name: 'Report a problem' })).toBeInTheDocument();
  });

  it('surfaces an error count badge when errors are captured', async () => {
    signIn();
    render(<ReportProblemHost />);
    pushReportEntry({ severity: 'error', source: 'console', message: 'boom' });
    expect(await screen.findByText('1')).toBeInTheDocument();
  });

  it('opens the report wizard when clicked', async () => {
    signIn();
    render(<ReportProblemHost />);
    fireEvent.click(screen.getByRole('button', { name: 'Report a problem' }));
    expect(await screen.findByText('What happened?')).toBeInTheDocument();
  });
});
