import { render, screen } from '@/test/test-utils';
import { StructureTab } from '../tabs/StructureTab';

vi.mock('@/components/dataset/AttributeMetadataTable', () => ({
  AttributeMetadataTable: () => <div data-testid="attribute-metadata-table" />,
}));
vi.mock('@/components/dataset/SchemaEditor', () => ({
  SchemaEditor: () => null,
}));

const defaultProps = {
  datasetId: 'ds-1',
  canEdit: false,
  columnInfo: [{ name: 'col1', type: 'text' }],
  capability: { editable: false, reason: 'read-only' } as never,
};

describe('StructureTab', () => {
  it('renders attribute metadata table', () => {
    render(<StructureTab {...defaultProps} />);

    expect(screen.getByTestId('attribute-metadata-table')).toBeInTheDocument();
  });

  it('does not render data preview (moved to Data tab)', () => {
    render(<StructureTab {...defaultProps} />);

    expect(screen.queryByTestId('attribute-table')).not.toBeInTheDocument();
  });

  it('uses a level-two title and places the edit control in the card action slot', () => {
    render(
      <StructureTab
        {...defaultProps}
        canEdit
        capability={{ editable: true } as never}
      />,
    );

    expect(
      screen.getByRole('heading', { level: 2, name: 'Attribute Metadata' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Manage Columns' }).closest('[data-slot="card-action"]'),
    ).toBeInTheDocument();
  });
});
