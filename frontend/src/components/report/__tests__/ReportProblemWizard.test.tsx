import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@/test/test-utils';
import { ReportProblemWizard } from '../ReportProblemWizard';
import { clearReportEntries, getReportEntries, pushReportEntry } from '@/lib/report';
import type { ReportEntry } from '@/lib/report';

function makeEntry(overrides: Partial<ReportEntry> = {}): ReportEntry {
  return {
    id: 'e1',
    ts: Date.now(),
    severity: 'error',
    source: 'console',
    message: 'TypeError: boom',
    count: 1,
    ...overrides,
  };
}

let writeTextMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearReportEntries();
  writeTextMock = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    configurable: true,
  });
});

describe('ReportProblemWizard', () => {
  it('copies technical details from step 1 without requiring any typed field', async () => {
    render(<ReportProblemWizard open onOpenChange={() => {}} entries={[makeEntry()]} />);

    fireEvent.click(screen.getByRole('button', { name: /copy technical details/i }));

    await waitFor(() => expect(writeTextMock).toHaveBeenCalledOnce());
    const [copied] = writeTextMock.mock.calls[0] as [string];
    expect(copied).toContain('## GeoLens technical details');
    expect(copied).toContain('TypeError: boom');
    expect(copied).toContain('**Browser:**');
  });

  it('clears the captured buffer from the technical-details row', () => {
    pushReportEntry({ severity: 'error', source: 'console', message: 'boom' });
    expect(getReportEntries()).toHaveLength(1);

    render(<ReportProblemWizard open onOpenChange={() => {}} entries={getReportEntries()} />);
    fireEvent.click(screen.getByRole('button', { name: /clear captured signals/i }));

    expect(getReportEntries()).toHaveLength(0);
  });

  it('hides the clear button when nothing is captured', () => {
    render(<ReportProblemWizard open onOpenChange={() => {}} entries={[]} />);
    expect(screen.queryByRole('button', { name: /clear captured signals/i })).toBeNull();
    // The copy affordance stays available — env/page context is still useful.
    expect(screen.getByRole('button', { name: /copy technical details/i })).toBeInTheDocument();
  });

  it('preserves an unsent draft across close and reopen', () => {
    const { rerender } = render(
      <ReportProblemWizard open onOpenChange={() => {}} entries={[]} />,
    );

    fireEvent.change(screen.getByLabelText(/what went wrong\?/i), {
      target: { value: 'The map went blank' },
    });

    rerender(<ReportProblemWizard open={false} onOpenChange={() => {}} entries={[]} />);
    rerender(<ReportProblemWizard open onOpenChange={() => {}} entries={[]} />);

    expect(screen.getByLabelText(/what went wrong\?/i)).toHaveValue('The map went blank');
  });

  it('starts clean again after the report is sent', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null);
    const { rerender } = render(
      <ReportProblemWizard open onOpenChange={() => {}} entries={[]} />,
    );

    fireEvent.change(screen.getByLabelText(/what went wrong\?/i), {
      target: { value: 'The map went blank' },
    });
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(await screen.findByRole('button', { name: /open a github issue/i }));
    expect(windowOpen).toHaveBeenCalledOnce();

    rerender(<ReportProblemWizard open={false} onOpenChange={() => {}} entries={[]} />);
    rerender(<ReportProblemWizard open onOpenChange={() => {}} entries={[]} />);

    expect(screen.getByLabelText(/what went wrong\?/i)).toHaveValue('');
    windowOpen.mockRestore();
  });
});
