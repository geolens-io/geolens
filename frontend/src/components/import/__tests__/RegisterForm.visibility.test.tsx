import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { RegisterForm } from '../RegisterForm';

const mockBulkRegister = vi.fn();
const settings = vi.hoisted(() => ({ canSetPublic: true }));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useDiscoverTables: () => ({
    data: {
      tables: [{ table_name: 'parcels', geometry_type: 'Polygon', srid: 4326, estimated_rows: 10 }],
    },
    isLoading: false,
    error: null,
  }),
  useDatasetCountHint: () => ({ data: undefined }),
  useBulkRegister: () => ({ mutateAsync: mockBulkRegister, isPending: false }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useCanSetPublicVisibility: () => settings.canSetPublic,
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  settings.canSetPublic = true;
  mockBulkRegister.mockReset();
  mockBulkRegister.mockResolvedValue({ results: [] });
});

async function openVisibility(user: ReturnType<typeof userEvent.setup>) {
  render(<RegisterForm />);
  await user.click(screen.getByText('parcels'));
  await user.click(screen.getByLabelText('register.visibilityLabel'));
  return screen.findAllByRole('option');
}

describe('RegisterForm visibility choices', () => {
  it('offers private, internal and public in that order', async () => {
    const options = await openVisibility(userEvent.setup());

    expect(options.map((o) => o.textContent)).toEqual([
      'register.visibilityPrivate',
      'register.visibilityInternal',
      'register.visibilityPublic',
    ]);
  });

  it('drops public but keeps internal when public is restricted', async () => {
    settings.canSetPublic = false;
    const options = await openVisibility(userEvent.setup());

    expect(options.map((o) => o.textContent)).toEqual([
      'register.visibilityPrivate',
      'register.visibilityInternal',
    ]);
  });

  it('sends the internal choice with the register request', async () => {
    const user = userEvent.setup();
    await openVisibility(user);
    await user.click(screen.getByRole('option', { name: 'register.visibilityInternal' }));
    await user.click(screen.getByRole('button', { name: 'register.registerButton' }));

    expect(mockBulkRegister).toHaveBeenCalledWith({
      tables: [expect.objectContaining({ table_name: 'parcels', visibility: 'internal' })],
    });
  });
});
