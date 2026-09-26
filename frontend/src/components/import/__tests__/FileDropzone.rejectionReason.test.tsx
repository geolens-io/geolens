/** react-dropzone's own FileError.message is English-only; the rejection
 *  toast must show a translated reason instead of that library text. */
import i18n from 'i18next';
import { render, screen, waitFor } from '@/test/test-utils';
import { changeTestLanguage } from '@/test/i18n';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { FileDropzone } from '../FileDropzone';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

describe('FileDropzone rejection reason', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates a too-large rejection instead of react-dropzone\'s English message', async () => {
    await changeTestLanguage('es');
    const user = userEvent.setup({ applyAccept: false });
    render(<FileDropzone onFilesAccepted={() => {}} maxSizeMb={1} />);

    const oversized = new File([new Uint8Array(2 * 1024 * 1024)], 'parcels.gpkg');
    await user.upload(screen.getByLabelText(i18n.t('import:dropzone.ariaLabel')), oversized);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const message = vi.mocked(toast.error).mock.calls[0][0] as string;

    expect(message).toContain(i18n.t('import:dropzone.rejectionReason.fileTooLarge', { size: 1 }));
    expect(message).not.toMatch(/larger than/i);
  });
});
