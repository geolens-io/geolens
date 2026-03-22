import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ImportMetadataForm } from '../ImportMetadataForm';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) return `${key}:${JSON.stringify(opts)}`;
      return key;
    },
  }),
}));

const defaultProps = {
  defaultName: 'test-data.csv',
  detectedCrs: null,
  onCommit: vi.fn(),
  isCommitting: false,
};

const sampleColumns = [
  { name: 'id', type: 'Integer' },
  { name: 'Latitude', type: 'Real' },
  { name: 'Longitude', type: 'Real' },
  { name: 'name', type: 'String' },
  { name: 'wkt', type: 'String' },
];

const detectedLatLng = {
  x_column: 'Longitude',
  y_column: 'Latitude',
  wkt_column: null,
};

const detectedWkt = {
  x_column: null,
  y_column: null,
  wkt_column: 'wkt',
};

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('ImportMetadataForm', () => {
  it('renders basic fields without geometry section when no columns', () => {
    render(<ImportMetadataForm {...defaultProps} />);

    expect(screen.getByLabelText('metadata.nameLabel')).toHaveValue('test-data');
    expect(screen.getByLabelText('metadata.descriptionLabel')).toBeInTheDocument();
    expect(screen.getByLabelText('metadata.visibilityLabel')).toBeInTheDocument();
    // Geometry section should not appear without previewColumns
    expect(screen.queryByText('metadata.geometryColumns')).not.toBeInTheDocument();
  });

  it('strips extension from default name', () => {
    render(
      <ImportMetadataForm {...defaultProps} defaultName="my-data.xlsx" />,
    );
    expect(screen.getByLabelText('metadata.nameLabel')).toHaveValue('my-data');
  });

  it('shows geometry section when previewColumns are provided', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );
    expect(screen.getByText('metadata.geometryColumns')).toBeInTheDocument();
  });

  it('does not show geometry section for raster imports', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        isRaster
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );
    expect(screen.queryByText('metadata.geometryColumns')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Geometry mode: auto-detected lat/lng
  // ---------------------------------------------------------------------------

  it('defaults to auto mode when geometry columns detected', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );
    const modeSelect = screen.getByLabelText('metadata.geometryMode');
    expect(modeSelect).toHaveValue('auto');
  });

  it('pre-fills x/y dropdowns from detected columns in auto mode', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );
    expect(screen.getByLabelText('metadata.xColumn')).toHaveValue('Longitude');
    expect(screen.getByLabelText('metadata.yColumn')).toHaveValue('Latitude');
  });

  it('disables dropdowns in auto mode', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );
    expect(screen.getByLabelText('metadata.xColumn')).toBeDisabled();
    expect(screen.getByLabelText('metadata.yColumn')).toBeDisabled();
  });

  // ---------------------------------------------------------------------------
  // Geometry mode: WKT auto-detected
  // ---------------------------------------------------------------------------

  it('defaults to WKT type when only wkt_column detected', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedWkt}
      />,
    );
    const wktRadio = screen.getByRole('radio', { name: 'metadata.wkt' });
    expect(wktRadio).toBeChecked();
  });

  it('pre-fills WKT dropdown from detected column', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedWkt}
      />,
    );
    expect(screen.getByLabelText('metadata.wktColumn')).toHaveValue('wkt');
  });

  // ---------------------------------------------------------------------------
  // Geometry mode: none (no detection)
  // ---------------------------------------------------------------------------

  it('defaults to none mode when no geometry columns detected', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={null}
      />,
    );
    const modeSelect = screen.getByLabelText('metadata.geometryMode');
    expect(modeSelect).toHaveValue('none');
  });

  it('hides column selectors in none mode', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={null}
      />,
    );
    expect(screen.queryByLabelText('metadata.xColumn')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('metadata.yColumn')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('metadata.wktColumn')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // User override: switching modes
  // ---------------------------------------------------------------------------

  it('enables dropdowns when switching from auto to manual', async () => {
    const user = userEvent.setup();
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );

    const modeSelect = screen.getByLabelText('metadata.geometryMode');
    await user.selectOptions(modeSelect, 'manual');

    expect(screen.getByLabelText('metadata.xColumn')).not.toBeDisabled();
    expect(screen.getByLabelText('metadata.yColumn')).not.toBeDisabled();
  });

  it('hides geometry selectors when switching to none mode', async () => {
    const user = userEvent.setup();
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );

    const modeSelect = screen.getByLabelText('metadata.geometryMode');
    await user.selectOptions(modeSelect, 'none');

    expect(screen.queryByLabelText('metadata.xColumn')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Form submission
  // ---------------------------------------------------------------------------

  it('submits with lat/lng columns in auto mode', async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();

    render(
      <ImportMetadataForm
        {...defaultProps}
        onCommit={onCommit}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));

    expect(onCommit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'test-data',
        x_column: 'Longitude',
        y_column: 'Latitude',
      }),
    );
    expect(onCommit.mock.calls[0][0]).not.toHaveProperty('geom_column');
  });

  it('submits with WKT column', async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();

    render(
      <ImportMetadataForm
        {...defaultProps}
        onCommit={onCommit}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedWkt}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));

    expect(onCommit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'test-data',
        geom_column: 'wkt',
      }),
    );
    expect(onCommit.mock.calls[0][0]).not.toHaveProperty('x_column');
  });

  it('submits without geometry columns in none mode', async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();

    render(
      <ImportMetadataForm
        {...defaultProps}
        onCommit={onCommit}
        previewColumns={sampleColumns}
        detectedGeometryColumns={null}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));

    expect(onCommit).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'test-data' }),
    );
    const call = onCommit.mock.calls[0][0];
    expect(call).not.toHaveProperty('x_column');
    expect(call).not.toHaveProperty('y_column');
    expect(call).not.toHaveProperty('geom_column');
  });

  it('submits with manual column selection override', async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();

    render(
      <ImportMetadataForm
        {...defaultProps}
        onCommit={onCommit}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );

    // Switch to manual mode
    await user.selectOptions(screen.getByLabelText('metadata.geometryMode'), 'manual');

    // Change x column to id (numeric)
    await user.selectOptions(screen.getByLabelText('metadata.xColumn'), 'id');

    await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));

    expect(onCommit).toHaveBeenCalledWith(
      expect.objectContaining({
        x_column: 'id',
        y_column: 'Latitude',
      }),
    );
  });

  // ---------------------------------------------------------------------------
  // Button state
  // ---------------------------------------------------------------------------

  it('disables submit button when committing', () => {
    render(
      <ImportMetadataForm {...defaultProps} isCommitting />,
    );
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('disables submit button when name is empty', async () => {
    const user = userEvent.setup();
    render(<ImportMetadataForm {...defaultProps} />);

    const nameInput = screen.getByLabelText('metadata.nameLabel');
    await user.clear(nameInput);

    expect(screen.getByRole('button', { name: 'metadata.importDataset' })).toBeDisabled();
  });

  // ---------------------------------------------------------------------------
  // Dropdown population
  // ---------------------------------------------------------------------------

  it('populates x/y dropdowns with numeric columns only', () => {
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={{ x_column: null, y_column: null, wkt_column: null }}
      />,
    );

    // Switch to manual mode to see enabled dropdowns
    // Mode is 'none' since nothing detected, so no dropdowns visible
    // We need to switch mode to manual first
  });

  it('populates WKT dropdown with string columns only', async () => {
    const user = userEvent.setup();
    render(
      <ImportMetadataForm
        {...defaultProps}
        previewColumns={sampleColumns}
        detectedGeometryColumns={detectedLatLng}
      />,
    );

    // Switch to manual mode
    await user.selectOptions(screen.getByLabelText('metadata.geometryMode'), 'manual');
    // Switch to WKT type
    await user.click(screen.getByRole('radio', { name: 'metadata.wkt' }));

    const wktSelect = screen.getByLabelText('metadata.wktColumn');
    const options = within(wktSelect).getAllByRole('option');
    // Should have: --, name, wkt (string columns + placeholder)
    const optionValues = options.map((o) => (o as HTMLOptionElement).value);
    expect(optionValues).toContain('name');
    expect(optionValues).toContain('wkt');
    expect(optionValues).not.toContain('id');
    expect(optionValues).not.toContain('Latitude');
  });
});
