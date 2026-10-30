import { useState, type ComponentProps } from 'react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router';
import { render, screen, waitFor, within } from '@/test/test-utils';
import { StoryCreateDialog } from '../StoryCreateDialog';
import { StoryDetailsDialog } from '../editor/StoryDetailsDialog';
import { MarkdownField } from '../editor/MarkdownField';
import { createStory, updateStory, uploadStoryImage } from '@/api/stories';
import { ApiError } from '@/api/client';
import type { StoryDraftResponse, StoryResponse } from '@/types/api';

vi.mock('@/api/stories', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/stories')>()),
  createStory: vi.fn(),
  updateStory: vi.fn(),
  uploadStoryImage: vi.fn(),
}));
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/webp' })),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/api/groups', () => ({ listMyGroups: vi.fn(async () => []) }));

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

const DRAFT: StoryDraftResponse = {
  id: 's1',
  title: 'Hurricanes',
  summary: null,
  visibility: 'private',
  created_by: 'me',
  published_at: null,
  cover_asset_id: null,
  created_at: '2026-10-29T00:00:00Z',
  updated_at: '2026-10-29T00:00:00Z',
  can_edit: true,
  revision: 1,
  document: { version: 1, chapters: [] },
};

function renderDetails(props: Partial<ComponentProps<typeof StoryDetailsDialog>> = {}) {
  return render(
    <StoryDetailsDialog story={DRAFT} open onOpenChange={() => {}} onSaved={vi.fn()} onGroupsSaved={vi.fn()} {...props} />,
  );
}

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

describe('StoryCreateDialog', () => {
  it('creates a story from the trimmed title and opens it in the editor', async () => {
    vi.mocked(createStory).mockResolvedValue({ ...DRAFT, id: 'new-story' });
    const user = userEvent.setup();
    render(
      <Routes>
        <Route path="*" element={<><StoryCreateDialog open onOpenChange={() => {}} /><Where /></>} />
      </Routes>,
      { route: '/maps' },
    );
    const create = screen.getByRole('button', { name: 'Create and edit' });
    expect(create).toBeDisabled();
    await user.type(screen.getByLabelText('Title'), '  Storm season  ');
    await user.click(create);
    await waitFor(() => expect(createStory).toHaveBeenCalledWith({ title: 'Storm season', summary: null }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/stories/new-story/edit'));
  });
});

describe('StoryDetailsDialog', () => {
  it('sends only the fields that changed', async () => {
    vi.mocked(updateStory).mockResolvedValue({ ...DRAFT, title: 'Storms', document: null } as StoryResponse);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderDetails({ onSaved });
    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Storms');
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    await waitFor(() => expect(updateStory).toHaveBeenCalledWith('s1', { title: 'Storms' }));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ title: 'Storms' }));
  });

  it('starts from the story again each time it opens', async () => {
    const user = userEvent.setup();
    const props = { story: DRAFT, onOpenChange: () => {}, onSaved: vi.fn(), onGroupsSaved: vi.fn() };
    const { rerender } = render(<StoryDetailsDialog {...props} open />);
    await user.type(screen.getByLabelText('Title'), ' typed');
    rerender(<StoryDetailsDialog {...props} open={false} />);
    rerender(<StoryDetailsDialog {...props} open />);
    expect(screen.getByLabelText('Title')).toHaveValue('Hurricanes');
  });

  it('names the maps that block a wider visibility and keeps the dialog open', async () => {
    vi.mocked(updateStory).mockRejectedValue(
      new ApiError('Conflict', 409, {
        code: 'maps_narrower_than_story',
        maps: [{ id: 'm1', name: 'Internal tracks' }],
        unreadable_maps: 0,
      }),
    );
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderDetails({ onOpenChange });
    await user.click(screen.getByRole('combobox', { name: 'Who can read it' }));
    await user.click(await screen.findByRole('option', { name: 'Public' }));
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    const alert = await screen.findByRole('alert');
    expect(updateStory).toHaveBeenCalledWith('s1', { visibility: 'public' });
    expect(within(alert).getByRole('link', { name: 'Internal tracks' })).toHaveAttribute('href', '/maps/m1');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

describe('StoryDetailsDialog cover', () => {
  const COVER = '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60';

  it('uploads a cover and saves it with the details', async () => {
    vi.mocked(uploadStoryImage).mockResolvedValue({
      id: COVER,
      width: 1200,
      height: 600,
      byte_size: 1000,
      created_at: '2026-10-29T00:00:00Z',
    });
    vi.mocked(updateStory).mockResolvedValue({ ...DRAFT, cover_asset_id: COVER, document: null } as StoryResponse);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderDetails({ onSaved });
    expect(screen.getByText('No cover image.')).toBeInTheDocument();
    await user.upload(screen.getByTestId('story-image-input'), new File(['png'], 'cover.png', { type: 'image/png' }));
    expect(await screen.findByRole('img', { name: 'Cover image preview' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    await waitFor(() => expect(updateStory).toHaveBeenCalledWith('s1', { cover_asset_id: COVER }));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ cover_asset_id: COVER }));
  });

  it('keeps Save details disabled while the cover is still uploading', async () => {
    let finish!: () => void;
    vi.mocked(uploadStoryImage).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () =>
            resolve({ id: COVER, width: 1200, height: 600, byte_size: 1000, created_at: '2026-10-29T00:00:00Z' });
        }),
    );
    vi.mocked(updateStory).mockResolvedValue({ ...DRAFT, cover_asset_id: COVER, document: null } as StoryResponse);
    const user = userEvent.setup();
    renderDetails();
    const save = screen.getByRole('button', { name: 'Save details' });
    expect(save).toBeEnabled();

    await user.upload(screen.getByTestId('story-image-input'), new File(['png'], 'cover.png', { type: 'image/png' }));
    await waitFor(() => expect(save).toBeDisabled());
    finish();
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(updateStory).toHaveBeenCalledWith('s1', { cover_asset_id: COVER }));
  });

  it('clears the cover', async () => {
    vi.mocked(updateStory).mockResolvedValue({ ...DRAFT, document: null } as StoryResponse);
    const user = userEvent.setup();
    renderDetails({ story: { ...DRAFT, cover_asset_id: COVER } });
    await user.click(screen.getByRole('button', { name: 'Remove cover image' }));
    expect(screen.getByText('No cover image.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    await waitFor(() => expect(updateStory).toHaveBeenCalledWith('s1', { cover_asset_id: null }));
  });
});

describe('MarkdownField', () => {
  it('bolds the selected text from the toolbar', async () => {
    const user = userEvent.setup();
    render(<MarkdownFieldHarness initial="a big storm" />);
    const textarea = screen.getByLabelText('Text block 1') as HTMLTextAreaElement;
    textarea.setSelectionRange(2, 5);
    await user.click(screen.getByRole('button', { name: 'Bold' }));
    expect(textarea).toHaveValue('a **big** storm');
    expect(textarea.value.slice(textarea.selectionStart, textarea.selectionEnd)).toBe('big');
  });

  it('previews the text through the Markdown block renderer', async () => {
    const user = userEvent.setup();
    render(<MarkdownFieldHarness initial="**Landfall** in Florida" />);
    await user.click(screen.getByRole('tab', { name: 'Preview' }));
    const strong = await screen.findByText('Landfall');
    expect(strong.tagName).toBe('STRONG');
  });
});

function MarkdownFieldHarness({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  return <MarkdownField blockId="00000000-0000-4000-8000-000000000001" label="Text block 1" value={value} onChange={setValue} />;
}
