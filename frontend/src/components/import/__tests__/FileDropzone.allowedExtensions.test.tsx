/** An empty list of extensions allows no file, while a list not yet loaded allows any. */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { FileDropzone } from '../FileDropzone';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

describe('FileDropzone', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rejects every file when its list of extensions is empty', async () => {
    const onFilesAccepted = vi.fn();
    const user = userEvent.setup({ applyAccept: false });
    render(<FileDropzone onFilesAccepted={onFilesAccepted} allowedExtensions={[]} />);

    await user.upload(screen.getByLabelText('Upload files'), new File(['PK'], 'campus.zip'));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onFilesAccepted).not.toHaveBeenCalled();
  });

  it('accepts a file while its list of extensions is still loading', async () => {
    const onFilesAccepted = vi.fn();
    const user = userEvent.setup({ applyAccept: false });
    render(<FileDropzone onFilesAccepted={onFilesAccepted} />);

    await user.upload(screen.getByLabelText('Upload files'), new File(['PK'], 'campus.zip'));

    await waitFor(() => expect(onFilesAccepted).toHaveBeenCalledTimes(1));
    expect(toast.error).not.toHaveBeenCalled();
  });
});
