import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { BuilderDialogs } from '../BuilderDialogs';
import type { MapResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('../DatasetSearchPanel', () => ({
  DatasetSearchPanel: ({ onAddDataset }: { onAddDataset: (id: string) => void }) => (
    <button type="button" onClick={() => onAddDataset('ds-1')}>
      Add to map
    </button>
  ),
}));

const mapData = { id: 'map-1', visibility: 'private' } as MapResponse;

function Harness({
  onOutsideClick,
  onPointerDownOutside,
  onAddDataset = () => {},
}: {
  onOutsideClick: () => void;
  onPointerDownOutside?: () => void;
  onAddDataset?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open add data
      </button>
      <button type="button" onClick={onOutsideClick}>
        Layer editor
      </button>
      <BuilderDialogs
        mapData={mapData}
        showAddData={open}
        onShowAddDataChange={setOpen}
        onAddDataset={onAddDataset}
        onAddDataPointerDownOutside={onPointerDownOutside}
        onDuplicateRendering={() => {}}
        layers={[]}
        isAdding={false}
        showShare={false}
        onShowShareChange={() => {}}
        hasUnsavedChanges={false}
        saveStatus="saved"
        showInfo={false}
        onShowInfoChange={() => {}}
        blockerState="unblocked"
      />
    </>
  );
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Open add data' }));
  return screen.findByRole('dialog');
}

describe('BuilderDialogs Add data dialog', () => {
  it('stays open after Add to map', async () => {
    const user = userEvent.setup();
    const onAddDataset = vi.fn();
    render(<Harness onOutsideClick={() => {}} onAddDataset={onAddDataset} />);
    await openDialog(user);

    await user.click(await screen.findByRole('button', { name: 'Add to map' }));

    expect(onAddDataset).toHaveBeenCalledWith('ds-1');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes on the first outside click and the click reaches its target', async () => {
    const user = userEvent.setup();
    const onOutsideClick = vi.fn();
    const onPointerDownOutside = vi.fn();
    render(<Harness onOutsideClick={onOutsideClick} onPointerDownOutside={onPointerDownOutside} />);
    await openDialog(user);
    await user.click(await screen.findByRole('button', { name: 'Add to map' }));

    await user.click(screen.getByRole('button', { name: 'Layer editor' }));

    expect(onOutsideClick).toHaveBeenCalledTimes(1);
    expect(onPointerDownOutside).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('does not hide the rest of the page from assistive tech', async () => {
    const user = userEvent.setup();
    render(<Harness onOutsideClick={() => {}} />);
    await openDialog(user);

    expect(screen.getByRole('button', { name: 'Layer editor' })).toBeVisible();
    expect(document.querySelector('[aria-hidden="true"][data-aria-hidden]')).toBeNull();
  });

  it('closes on Escape and returns focus to the opener', async () => {
    const user = userEvent.setup();
    render(<Harness onOutsideClick={() => {}} />);
    await openDialog(user);

    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Open add data' })).toHaveFocus(),
    );
  });

  it('closes from the Close button and returns focus to the opener', async () => {
    const user = userEvent.setup();
    render(<Harness onOutsideClick={() => {}} />);
    const dialog = await openDialog(user);

    await user.click(screen.getByRole('button', { name: 'close' }));

    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Open add data' })).toHaveFocus(),
    );
  });
});
