import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useValidation } from '@/hooks/use-dataset';
import { ValidationStatus } from '@/components/dataset/ValidationStatus';
import type { ValidationIssue } from '@/types/api';

vi.mock('@/hooks/use-dataset', () => ({
  useValidation: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useAllSettings: () => ({
    data: {
      tabs: {
        general: [],
      },
    },
  }),
}));

const mockUseValidation = vi.mocked(useValidation);

function createValidationResult({
  isValid = true,
  errors = [],
  warnings = [],
}: {
  isValid?: boolean;
  errors?: ValidationIssue[];
  warnings?: ValidationIssue[];
} = {}): ReturnType<typeof useValidation> {
  return {
    data: {
      is_valid: isValid,
      errors,
      warnings,
      quality_score: null,
    },
    isLoading: false,
  } as ReturnType<typeof useValidation>;
}

describe('ValidationStatus', () => {
  beforeEach(() => {
    mockUseValidation.mockReturnValue(createValidationResult());
  });

  it('renders helper guidance and likely causes when warnings/errors exist', () => {
    mockUseValidation.mockReturnValue(
      createValidationResult({
        isValid: false,
        errors: [
          { field: 'source_url', message: 'Missing source URL', severity: 'error' },
          { field: 'source_url', message: 'Source URL is required', severity: 'error' },
        ],
        warnings: [
          { field: 'update_frequency', message: 'Missing update cadence', severity: 'warning' },
        ],
      }),
    );

    render(<ValidationStatus datasetId="dataset-1" />);

    expect(screen.getByTestId('validation-helper-text')).toHaveTextContent(/issue\(s\).*warning\(s\).*need attention/i);
    expect(screen.getByTestId('validation-likely-causes')).toHaveTextContent(/Missing Source Url/i);
    expect(screen.getByTestId('validation-likely-causes')).toHaveTextContent(/Missing Update Frequency/i);
    expect(screen.getByTestId('validation-troubleshoot-trigger')).toBeInTheDocument();
  });

  it('opens and closes the in-app troubleshoot dialog from inline trigger', async () => {
    const user = userEvent.setup();
    mockUseValidation.mockReturnValue(
      createValidationResult({
        isValid: false,
        errors: [{ field: 'title', message: 'Title is required', severity: 'error' }],
      }),
    );

    render(<ValidationStatus datasetId="dataset-1" />);

    await user.click(screen.getByTestId('validation-troubleshoot-trigger'));

    expect(screen.getByTestId('validation-troubleshoot-dialog')).toBeInTheDocument();
    expect(screen.getByText(/validation troubleshooting/i)).toBeInTheDocument();
    expect(screen.getByTestId('validation-troubleshoot-errors')).toBeInTheDocument();

    await user.click(screen.getByTestId('validation-troubleshoot-close'));

    await waitFor(() => {
      expect(screen.queryByTestId('validation-troubleshoot-dialog')).not.toBeInTheDocument();
    });
  });

  it('offers field navigation from troubleshoot for issues with known destinations', async () => {
    const user = userEvent.setup();
    const onNavigateToField = vi.fn();
    mockUseValidation.mockReturnValue(
      createValidationResult({
        isValid: false,
        errors: [{ field: 'summary', message: 'Summary is required', severity: 'error' }],
      }),
    );

    render(
      <ValidationStatus
        datasetId="dataset-1"
        onNavigateToField={onNavigateToField}
      />,
    );

    await user.click(screen.getByTestId('validation-troubleshoot-trigger'));
    await user.click(screen.getByRole('button', { name: 'Go to field' }));

    expect(onNavigateToField).toHaveBeenCalledWith('summary');
  });

  it('does not show troubleshoot affordance for clean datasets', () => {
    mockUseValidation.mockReturnValue(createValidationResult({ isValid: true }));

    render(<ValidationStatus datasetId="dataset-1" />);

    expect(screen.getByText(/ready to publish/i)).toBeInTheDocument();
    expect(screen.queryByTestId('validation-helper-text')).not.toBeInTheDocument();
    expect(screen.queryByTestId('validation-troubleshoot-trigger')).not.toBeInTheDocument();
  });

  it('keeps compact mode concise while still exposing troubleshoot action for warnings', () => {
    mockUseValidation.mockReturnValue(
      createValidationResult({
        isValid: true,
        warnings: [{ field: 'lineage_summary', message: 'Missing lineage summary', severity: 'warning' }],
      }),
    );

    render(<ValidationStatus datasetId="dataset-1" mode="compact" />);

    expect(screen.getByTestId('validation-status-compact')).toBeInTheDocument();
    expect(screen.getByTestId('validation-likely-causes-compact')).toHaveTextContent(/Likely:/i);
    expect(screen.getByTestId('validation-troubleshoot-trigger')).toBeInTheDocument();
  });
});
