import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { useValidation } from '@/hooks/use-dataset';
import { DatasetHealthStrip } from '@/components/dataset/DatasetHealthStrip';
import type { ValidationIssue } from '@/types/api';

vi.mock('@/hooks/use-dataset', () => ({
  useValidation: vi.fn(),
}));

const mockUseValidation = vi.mocked(useValidation);

function createValidationResult({
  errors = [],
  warnings = [],
}: {
  errors?: ValidationIssue[];
  warnings?: ValidationIssue[];
} = {}): ReturnType<typeof useValidation> {
  return {
    data: {
      is_valid: errors.length === 0,
      errors,
      warnings,
      quality_score: null,
    },
    isLoading: false,
  } as ReturnType<typeof useValidation>;
}

describe('DatasetHealthStrip', () => {
  beforeEach(() => {
    mockUseValidation.mockReturnValue(createValidationResult());
  });

  it('renders counts and top review actions for validation issues', async () => {
    const user = userEvent.setup();
    const onNavigateToField = vi.fn();

    mockUseValidation.mockReturnValue(
      createValidationResult({
        errors: [
          { field: 'summary', message: 'Summary is required', severity: 'error' },
          { field: 'contacts', message: 'At least one contact is required', severity: 'error' },
        ],
        warnings: [
          { field: 'source_url', message: 'Source URL is recommended', severity: 'warning' },
          { field: 'quality_statement', message: 'Quality statement is recommended', severity: 'warning' },
          { field: 'attribute_descriptions', message: 'Attribute descriptions are recommended', severity: 'warning' },
        ],
      }),
    );

    render(<DatasetHealthStrip datasetId="dataset-1" onNavigateToField={onNavigateToField} />);

    expect(screen.getByTestId('dataset-health-strip')).toBeInTheDocument();
    expect(screen.getByText('Required 2')).toBeInTheDocument();
    expect(screen.getByText('Recommended 3')).toBeInTheDocument();
    expect(screen.getByText(/required item\(s\) and 3 recommended item\(s\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review summary' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review contacts' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Review summary' }));

    expect(onNavigateToField).toHaveBeenCalledWith('summary');
  });

  it('renders the healthy state when validation is clear', () => {
    render(<DatasetHealthStrip datasetId="dataset-1" onNavigateToField={vi.fn()} />);

    expect(screen.getByText('On track')).toBeInTheDocument();
    expect(screen.getByText('No active validation issues detected.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /review/i })).not.toBeInTheDocument();
  });
});
