import { render, screen, fireEvent, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { StyleJsonDialog } from '../StyleJsonDialog';

const exportMutateAsync = vi.fn();
const importMutateAsync = vi.fn();

vi.mock('@/hooks/use-maps', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-maps')>('@/hooks/use-maps');
  return {
    ...actual,
    useExportMapStyleJson: () => ({ mutateAsync: exportMutateAsync, isPending: false }),
    useImportMapStyleJson: () => ({ mutateAsync: importMutateAsync, isPending: false }),
  };
});

describe('StyleJsonDialog', () => {
  beforeEach(() => {
    exportMutateAsync.mockReset();
    importMutateAsync.mockReset();
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:style'),
      revokeObjectURL: vi.fn(),
    });
  });

  it('exports the current map style as a JSON download', async () => {
    exportMutateAsync.mockResolvedValueOnce({ version: 8, sources: {}, layers: [] });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    render(<StyleJsonDialog mapId="map-1" mapName="Transit Map" open onOpenChange={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /export json/i }));

    await waitFor(() => expect(exportMutateAsync).toHaveBeenCalledWith('map-1'));
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it('shows inline validation for invalid import JSON', async () => {
    render(<StyleJsonDialog mapId="map-1" mapName="Transit Map" open onOpenChange={vi.fn()} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Import' }));
    fireEvent.change(screen.getByTestId('style-json-input'), { target: { value: '{' } });
    await userEvent.click(screen.getByRole('button', { name: /import json/i }));

    expect(screen.getByText('Invalid JSON.')).toBeInTheDocument();
    expect(importMutateAsync).not.toHaveBeenCalled();
  });

  it('renders import summary warnings returned by the backend', async () => {
    importMutateAsync.mockResolvedValueOnce({
      map: { id: 'new-map' },
      summary: {
        sources_matched: 1,
        sources_unsupported: 1,
        layers_imported: 2,
        layers_skipped: 1,
        warnings: [{ code: 'unsupported_source', message: 'External source skipped.' }],
      },
    });

    render(<StyleJsonDialog mapId="map-1" mapName="Transit Map" open onOpenChange={vi.fn()} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Import' }));
    fireEvent.change(screen.getByTestId('style-json-input'), {
      target: { value: '{"version":8,"sources":{},"layers":[]}' },
    });
    await userEvent.click(screen.getByRole('button', { name: /import json/i }));

    await waitFor(() => expect(importMutateAsync).toHaveBeenCalledWith({
      version: 8,
      sources: {},
      layers: [],
    }));
    expect(screen.getByText('Imported 2 layers')).toBeInTheDocument();
    expect(screen.getByText('External source skipped.')).toBeInTheDocument();
  });
});
