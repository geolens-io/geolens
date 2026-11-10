import { render, screen } from '@/test/test-utils';
import type { MapLayerAccessGap } from '@/types/api';
import { MapShareConfirmDialog } from '../MapShareConfirmDialog';

function gap(layerTitle: string, datasetTitle: string): MapLayerAccessGap {
  return {
    layer_id: 'l-1',
    layer_title: layerTitle,
    dataset_id: 'd-1',
    dataset_title: datasetTitle,
    group_ids: ['g-1'],
    can_share: true,
  };
}

function setup(layer: MapLayerAccessGap) {
  render(
    <MapShareConfirmDialog
      layers={[layer]}
      groupNames={new Map([['g-1', 'Surveyors']])}
      pending={false}
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      onCloseFocus={vi.fn()}
    />,
  );
}

describe('MapShareConfirmDialog', () => {
  it('names the dataset when it differs from the layer title', () => {
    setup(gap('Parcels', 'Parcel data'));
    expect(screen.getByText('Parcels (dataset: Parcel data)')).toBeInTheDocument();
  });

  it('shows the title once when the layer and dataset share it', () => {
    setup(gap('Brooklyn Parcels', 'Brooklyn Parcels'));
    expect(screen.getByText('Brooklyn Parcels')).toBeInTheDocument();
    expect(screen.queryByText(/dataset:/)).not.toBeInTheDocument();
  });
});
