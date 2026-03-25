import { render, screen } from '@/test/test-utils';
import { StructureTab } from '../tabs/StructureTab';

vi.mock('@/components/dataset/AttributeTable', () => ({
  AttributeTable: () => <div data-testid="attribute-table" />,
}));
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
  tableName: 'my_table',
};

describe('StructureTab', () => {
  it('does NOT render Data Preview card for table datasets', () => {
    render(<StructureTab {...defaultProps} recordType="table" />);

    expect(screen.queryByTestId('attribute-table')).not.toBeInTheDocument();
  });

  it('renders Data Preview card for vector datasets (no recordType)', () => {
    render(<StructureTab {...defaultProps} />);

    expect(screen.getByTestId('attribute-table')).toBeInTheDocument();
  });

  it('renders Data Preview card for vector_dataset recordType', () => {
    render(<StructureTab {...defaultProps} recordType="vector_dataset" />);

    expect(screen.getByTestId('attribute-table')).toBeInTheDocument();
  });
});
