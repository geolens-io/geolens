import { useImperativeHandle, type Ref } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import userEvent from '@testing-library/user-event';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { StoryEditorPage } from '../StoryEditorPage';
import {
  discardStoryDraft,
  getStory,
  getStoryDraft,
  publishStory,
  saveStoryDraft,
  uploadStoryImage,
} from '@/api/stories';
import { ApiError } from '@/api/client';
import { listMaps } from '@/api/maps';
import { useAuthStore } from '@/stores/auth-store';
import type { ResolvedScene } from '@/components/stories/story-scenes';
import type { MapResponse, StoryChapter, StoryDraftResponse, StoryResponse } from '@/types/api';

vi.mock('@/api/stories', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/stories')>()),
  getStory: vi.fn(),
  getStoryDraft: vi.fn(),
  saveStoryDraft: vi.fn(),
  publishStory: vi.fn(),
  discardStoryDraft: vi.fn(),
  uploadStoryImage: vi.fn(),
}));
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/webp' })),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/api/maps', () => ({
  listMaps: vi.fn(async () => ({ maps: [{ id: 'map-a', name: 'Tracks', visibility: 'public' }], total: 1 })),
}));
vi.mock('sonner', () => ({ toast }));

const VIEW = { center: [-80.123457, 26.987654] as [number, number], zoom: 6.789, bearing: 10, pitch: 20 };
const pane = vi.hoisted(() => ({
  resolved: null as ResolvedScene | null,
  seen: [] as (ResolvedScene | null)[],
  resetKey: undefined as number | undefined,
}));
vi.mock('@/components/stories/StoryMapPane', () => ({
  StoryMapPane: ({
    resolved,
    emptyHint,
    resetKey,
    ref,
  }: {
    resolved: ResolvedScene | null;
    emptyHint?: string;
    resetKey?: number;
    ref?: Ref<{ getView: () => typeof VIEW }>;
  }) => {
    pane.resolved = resolved;
    pane.seen.push(resolved);
    pane.resetKey = resetKey;
    useImperativeHandle(ref, () => ({ getView: () => VIEW }));
    return resolved ? <div data-testid="story-map" /> : <p>{emptyHint}</p>;
  },
}));
const perm = vi.hoisted(() => ({ editMetadata: true }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => capability === 'edit_metadata' && perm.editMetadata,
    isLoading: false,
  }),
}));

const MAP = {
  id: 'map-a',
  name: 'Tracks',
  center_lng: -60.12345678,
  center_lat: 20,
  zoom: 3,
  bearing: 0,
  pitch: 0,
  layers: [
    { id: 'layer-1', display_name: 'Storm tracks', dataset_name: 'tracks', visible: true },
    { id: 'layer-2', display_name: 'Coasts', dataset_name: 'coasts', visible: false },
    { id: 'folder-1', display_name: 'Basins', dataset_name: 'basins', visible: true, layer_type: 'group:folder' },
  ],
} as unknown as MapResponse;
const mapFetch = vi.hoisted(() => ({ next: null as Promise<unknown> | null }));
vi.mock('@/hooks/use-maps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/hooks/use-maps')>()),
  useMap: (id: string | undefined) => ({ data: id === 'map-a' ? MAP : undefined }),
  mapDetailQuery: (id: string) => ({ queryKey: ['map', id], queryFn: () => mapFetch.next ?? Promise.resolve(MAP), retry: false }),
}));

function markdown(id: string, text: string) {
  return { id, type: 'markdown' as const, v: 1 as const, title: null, config: { text } };
}

const CHAPTERS: StoryChapter[] = [
  { id: 'c1', title: 'Opening', scene: null, scene_hidden: false, blocks: [markdown('b1', 'Hello')] },
  { id: 'c2', title: 'Second', scene: null, scene_hidden: false, blocks: [markdown('b2', 'More')] },
];

function draft(overrides: Partial<StoryDraftResponse> = {}): StoryDraftResponse {
  return {
    id: 's1',
    title: 'Hurricanes',
    summary: null,
    visibility: 'public',
    created_by: 'me',
    published_at: '2026-10-29T00:00:00Z',
    cover_asset_id: null,
    created_at: '2026-10-29T00:00:00Z',
    updated_at: '2026-10-29T00:00:00Z',
    can_edit: true,
    revision: 4,
    document: { version: 1, chapters: CHAPTERS },
    ...overrides,
  };
}

function published(chapters: StoryChapter[] = CHAPTERS): StoryResponse {
  const { revision: _revision, ...rest } = draft();
  return { ...rest, document: { version: 1, chapters } };
}

function renderEditor() {
  const router = createMemoryRouter(
    [
      { path: '/stories/:id/edit', element: <StoryEditorPage /> },
      { path: '/stories/:id', element: <p>reader page</p> },
    ],
    { initialEntries: ['/stories/s1/edit'] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return Object.assign(router, { client });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const ACCOUNT_B = {
  id: 'user-b',
  username: 'b',
  email: 'b@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  can_reset_password: true,
  created_at: '2026-01-01T00:00:00Z',
  roles: ['admin'],
};

/** Another account signing in: the auth store's new user, and the cache clear `wireAuthCacheReset` makes for it. */
function switchAccount(client: QueryClient) {
  act(() => {
    useAuthStore.setState((state) => ({ user: ACCOUNT_B as never, sessionEpoch: state.sessionEpoch + 1 }));
    client.clear();
  });
}

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  vi.mocked(getStoryDraft).mockResolvedValue(draft());
  vi.mocked(getStory).mockResolvedValue(published());
  vi.mocked(saveStoryDraft).mockImplementation(async (_id, revision, chapters) =>
    draft({ revision: revision + 1, document: { version: 1, chapters } }),
  );
  vi.mocked(publishStory).mockReset();
  vi.mocked(discardStoryDraft).mockReset();
  toast.success.mockReset();
  toast.error.mockReset();
  pane.resolved = null;
  pane.seen = [];
  pane.resetKey = undefined;
  perm.editMetadata = true;
  mapFetch.next = null;
});

afterEach(() => {
  useAuthStore.setState({ user: null });
});

/** Opens the map combobox and picks the first option matching `name`. */
async function pickMap(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  await user.click(screen.getByRole('combobox', { name: 'Map' }));
  await user.keyboard('{ArrowDown}');
  await user.click(await screen.findByRole('option', { name }));
}

async function ready() {
  await screen.findByRole('heading', { name: 'Hurricanes' });
  await screen.findByText('Published. Readers see this version.');
}

/** Hides the tab, which saves whatever is pending without waiting out the autosave delay. */
function saveNow() {
  const hidden = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  act(() => void document.dispatchEvent(new Event('visibilitychange')));
  hidden.mockRestore();
}

const lastSavedChapters = () => vi.mocked(saveStoryDraft).mock.lastCall![2];

it('saves edits to the draft against the revision it loaded', async () => {
  const user = userEvent.setup();
  renderEditor();
  await ready();
  expect(screen.queryByRole('button', { name: 'Save draft' })).not.toBeInTheDocument();

  const title = screen.getByLabelText('Chapter title');
  await user.clear(title);
  await user.type(title, 'Landfall');
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

  saveNow();
  await waitFor(() => expect(saveStoryDraft).toHaveBeenCalledWith('s1', 4, expect.any(Array)));
  expect(lastSavedChapters()[0].title).toBe('Landfall');
  expect(await screen.findByText('Draft saved. Readers still see the last published version.')).toBeInTheDocument();
});

it('adds, reorders and deletes chapters from the chapter list', async () => {
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const list = screen.getByRole('navigation', { name: 'Chapters' });

  await user.click(within(list).getByRole('button', { name: 'Move Second up' }));
  expect(within(list).getByRole('button', { name: 'Move Second down' })).toHaveFocus();
  await user.click(within(list).getByRole('button', { name: 'Add chapter' }));
  await user.click(within(list).getByRole('button', { name: 'Delete Opening' }));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete chapter' }));

  saveNow();
  await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
  const saved = lastSavedChapters();
  expect(saved.map((c) => c.title)).toEqual(['Second', null]);
});

it('picks a map, keeps the current view and sets the scene layers', async () => {
  const user = userEvent.setup();
  renderEditor();
  await ready();

  await pickMap(user, /^Tracks/);
  await screen.findByRole('button', { name: 'Use current view' });
  expect(pane.resolved?.scene).toMatchObject({
    map_id: 'map-a',
    camera: { center: [-60.123457, 20], zoom: 3, bearing: 0, pitch: 0 },
  });

  expect(screen.getByRole('checkbox', { name: 'Coasts' })).not.toBeChecked();
  expect(screen.queryByRole('checkbox', { name: 'Basins' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Use current view' }));
  await user.click(screen.getByRole('checkbox', { name: 'Storm tracks' }));
  saveNow();
  await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());

  expect(lastSavedChapters()[0].scene).toEqual({
    map_id: 'map-a',
    camera: VIEW,
    layer_visibility: { 'layer-1': false },
  });
});

it('saves unsaved edits before publishing, then publishes that revision', async () => {
  vi.mocked(publishStory).mockResolvedValue(published());
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.type(screen.getByLabelText('Chapter title'), '!');
  await user.click(screen.getByRole('button', { name: 'Publish' }));
  await waitFor(() => expect(publishStory).toHaveBeenCalledWith('s1', 5));
  expect(saveStoryDraft).toHaveBeenCalledWith('s1', 4, expect.any(Array));
  expect(toast.success).toHaveBeenCalledWith('Story published');
});

it('names the maps that keep the story from publishing', async () => {
  vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
  vi.mocked(publishStory).mockRejectedValue(
    new ApiError('Conflict', 409, {
      code: 'maps_narrower_than_story',
      maps: [{ id: 'map-p', name: 'Private tracks' }],
      unreadable_maps: 2,
    }),
  );
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText('Draft saved. Readers still see the last published version.');
  await user.click(screen.getByRole('button', { name: 'Publish' }));

  const dialog = await screen.findByRole('alertdialog', { name: 'Publishing was refused' });
  expect(within(dialog).getByRole('link', { name: 'Private tracks' })).toHaveAttribute('href', '/maps/map-p');
  expect(within(dialog).getByText("2 more maps you can't open")).toBeInTheDocument();
});

it('stops on a stale revision and reloads the latest draft on request', async () => {
  vi.mocked(saveStoryDraft).mockRejectedValue(
    new ApiError('Conflict', 409, { code: 'stale_revision', revision: 9 }),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('changed somewhere else');
  expect(toast.error).not.toHaveBeenCalled();

  vi.mocked(getStoryDraft).mockResolvedValue(draft({ revision: 9 }));
  await user.click(within(alert).getByRole('button', { name: 'Load latest' }));
  // Unsaved edits are at stake, so it asks first.
  const confirm = await screen.findByRole('alertdialog', { name: 'Load the latest version?' });
  expect(getStoryDraft).toHaveBeenCalledTimes(1);
  await user.click(within(confirm).getByRole('button', { name: 'Load latest' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.getByLabelText('Chapter title')).toHaveValue('Opening');
});

it('saves over a draft changed elsewhere at the revision the conflict reported, after a confirm', async () => {
  vi.mocked(saveStoryDraft).mockRejectedValueOnce(
    new ApiError('Conflict', 409, { code: 'stale_revision', revision: 9 }),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();
  const alert = await screen.findByRole('alert');

  await user.click(within(alert).getByRole('button', { name: 'Overwrite with my version' }));
  const confirm = await screen.findByRole('alertdialog', { name: 'Overwrite the other changes?' });
  expect(confirm).toHaveTextContent('Changes saved elsewhere since you opened it are lost.');
  expect(saveStoryDraft).toHaveBeenCalledTimes(1);
  await user.click(within(confirm).getByRole('button', { name: 'Overwrite with my version' }));

  await waitFor(() => expect(saveStoryDraft).toHaveBeenLastCalledWith('s1', 9, expect.any(Array)));
  expect(lastSavedChapters()[0].title).toBe('Opening!');
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});

it('tells the map to return to the scene camera after a discard or a reload, not after a save', async () => {
  vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
  vi.mocked(discardStoryDraft).mockResolvedValue(draft({ revision: 5, document: { version: 1, chapters: [CHAPTERS[0]] } }));
  vi.mocked(saveStoryDraft).mockRejectedValueOnce(new ApiError('Conflict', 409, { code: 'stale_revision', revision: 9 }));
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText('Draft saved. Readers still see the last published version.');
  const start = pane.resetKey;

  await user.click(screen.getByRole('button', { name: 'Discard draft' }));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard draft' }));
  await waitFor(() => expect(pane.resetKey).toBe(start! + 1));

  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();
  const alert = await screen.findByRole('alert');
  expect(pane.resetKey).toBe(start! + 1);
  await user.click(within(alert).getByRole('button', { name: 'Load latest' }));
  await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Load latest' }));
  await waitFor(() => expect(pane.resetKey).toBe(start! + 2));
});

it('discards the draft back to the published story after the confirm', async () => {
  vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
  vi.mocked(discardStoryDraft).mockResolvedValue(
    draft({ revision: 5, document: { version: 1, chapters: [CHAPTERS[0]] } }),
  );
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText('Draft saved. Readers still see the last published version.');

  await user.click(screen.getByRole('button', { name: 'Discard draft' }));
  expect(discardStoryDraft).not.toHaveBeenCalled();
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard draft' }));
  await waitFor(() => expect(discardStoryDraft).toHaveBeenCalledWith('s1', 4));
  expect(await screen.findByText('Published. Readers see this version.')).toBeInTheDocument();
});

/** Edits the title, then fails the save it triggers, so the edit stays unsaved. */
async function typeUnsavedEdit(user: ReturnType<typeof userEvent.setup>) {
  vi.mocked(saveStoryDraft).mockRejectedValue(new ApiError('Boom', 500));
  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();
  await screen.findByText("Couldn't save");
}

it('asks before leaving with unsaved changes', async () => {
  const user = userEvent.setup();
  const router = renderEditor();
  await ready();
  await typeUnsavedEdit(user);

  await user.click(screen.getByRole('link', { name: 'View story' }));
  const dialog = await screen.findByRole('alertdialog', { name: 'Leave without saving?' });
  await user.click(within(dialog).getByRole('button', { name: 'Keep editing' }));
  expect(router.state.location.pathname).toBe('/stories/s1/edit');
});

it("tells a reader who can't edit the story so", async () => {
  vi.mocked(getStoryDraft).mockRejectedValue(new ApiError('Forbidden', 403));
  renderEditor();
  expect(await screen.findByText("You can't edit this story")).toBeInTheDocument();
});

it("keeps a scene on a map the editor can't open until it's removed", async () => {
  const hidden = { ...CHAPTERS[0], scene_hidden: true };
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [hidden, CHAPTERS[1]] } }));
  vi.mocked(getStory).mockResolvedValue(published([hidden, CHAPTERS[1]]));
  const user = userEvent.setup();
  renderEditor();
  await ready();
  expect(screen.getByText(/map is unavailable or has been deleted/)).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: 'Remove scene' }));
  saveNow();
  await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
  expect(lastSavedChapters()[0]).toMatchObject({ scene: null, scene_hidden: false });
});

it('hints at choosing a map while no chapter has a scene', async () => {
  renderEditor();
  await ready();
  expect(screen.getByText('Choose a map for a chapter to see it here.')).toBeInTheDocument();
  expect(screen.queryByTestId('story-map')).not.toBeInTheDocument();
});

it('keeps the same scene object for the map pane while the chapter text changes', async () => {
  const withScene: StoryChapter = {
    ...CHAPTERS[0],
    scene: { map_id: 'map-a', camera: { center: [0, 0], zoom: 2, bearing: 0, pitch: 0 }, layer_visibility: {} },
  };
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [withScene, CHAPTERS[1]] } }));
  vi.mocked(getStory).mockResolvedValue(published([withScene, CHAPTERS[1]]));
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const before = pane.resolved;
  expect(before?.chapterId).toBe('c1');

  await user.type(screen.getByLabelText('Chapter title'), ' and more');
  await user.type(screen.getByLabelText('Text block 1'), ' words');
  expect(pane.seen.length).toBeGreaterThan(2);
  expect(pane.resolved).toBe(before);
});

it('leaves when the author confirms', async () => {
  const user = userEvent.setup();
  const router = renderEditor();
  await ready();
  await typeUnsavedEdit(user);
  await user.click(screen.getByRole('link', { name: 'View story' }));
  const dialog = await screen.findByRole('alertdialog', { name: 'Leave without saving?' });
  await user.click(within(dialog).getByRole('button', { name: 'Leave' }));
  await waitFor(() => expect(router.state.location.pathname).toBe('/stories/s1'));
});

it("doesn't open the editor without edit_metadata, even for the owner", async () => {
  perm.editMetadata = false;
  renderEditor();
  expect(await screen.findByText("You can't edit this story")).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Save draft' })).not.toBeInTheDocument();
});

it('keeps text typed while a save is in flight', async () => {
  let finish!: (value: StoryDraftResponse) => void;
  vi.mocked(saveStoryDraft).mockImplementationOnce(
    (_id, revision, chapters) =>
      new Promise((resolve) => {
        finish = () => resolve(draft({ revision: revision + 1, document: { version: 1, chapters } }));
      }),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const title = screen.getByLabelText('Chapter title');
  await user.type(title, ' A');
  saveNow();
  await user.type(title, 'B');
  finish(draft());
  await screen.findByText('Unsaved changes');
  expect(title).toHaveValue('Opening AB');
});

it("doesn't fetch the published copy of a story that was never published", async () => {
  vi.mocked(getStory).mockClear();
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ published_at: null }));
  renderEditor();
  expect(await screen.findByText('Draft saved. Not published yet.')).toBeInTheDocument();
  expect(getStory).not.toHaveBeenCalled();
});

describe('another account signing in mid-request', () => {
  const B_DRAFT = () => draft({ title: 'B view' });

  async function startThenSwitch(start: (user: ReturnType<typeof userEvent.setup>) => Promise<void>) {
    const user = userEvent.setup();
    const router = renderEditor();
    await ready();
    await start(user);
    vi.mocked(getStoryDraft).mockResolvedValue(B_DRAFT());
    vi.mocked(getStory).mockResolvedValue({ ...published(), title: 'B view' });
    switchAccount(router.client);
    await screen.findByRole('heading', { name: 'B view' });
    return router;
  }

  async function expectOnlyB(client: QueryClient) {
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(screen.getByRole('heading', { name: 'B view' })).toBeInTheDocument();
    expect(client.getQueryData<StoryDraftResponse>(['story', 's1', 'draft'])?.title).toBe('B view');
    const detail = client.getQueryData<StoryResponse>(['story', 's1']);
    expect(detail === undefined || detail.title === 'B view').toBe(true);
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  }

  it('drops a save that finishes afterwards', async () => {
    const gate = deferred<StoryDraftResponse>();
    vi.mocked(saveStoryDraft).mockReturnValueOnce(gate.promise);
    const { client } = await startThenSwitch(async (user) => {
      await user.type(screen.getByLabelText('Chapter title'), '!');
      saveNow();
    });
    gate.resolve(draft({ title: 'A late', revision: 5 }));
    await expectOnlyB(client);
  });

  it('drops a save that finishes in the same moment the account changes', async () => {
    const gate = deferred<StoryDraftResponse>();
    vi.mocked(saveStoryDraft).mockReturnValueOnce(gate.promise);
    const user = userEvent.setup();
    const { client } = renderEditor();
    await ready();
    await user.type(screen.getByLabelText('Chapter title'), '!');
    saveNow();
    vi.mocked(getStoryDraft).mockResolvedValue(B_DRAFT());
    vi.mocked(getStory).mockResolvedValue({ ...published(), title: 'B view' });
    await act(async () => {
      useAuthStore.setState({ user: ACCOUNT_B as never });
      client.clear();
      gate.resolve(draft({ title: 'A late', revision: 5 }));
      await Promise.resolve();
    });
    await screen.findByRole('heading', { name: 'B view' });
    await expectOnlyB(client);
  });

  it('drops a publish that finishes afterwards, and its follow-up read', async () => {
    vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
    const gate = deferred<StoryResponse>();
    vi.mocked(publishStory).mockReturnValueOnce(gate.promise);
    const user = userEvent.setup();
    const router = renderEditor();
    await screen.findByText('Draft saved. Readers still see the last published version.');
    await user.click(screen.getByRole('button', { name: 'Publish' }));
    vi.mocked(getStoryDraft).mockClear();
    vi.mocked(getStoryDraft).mockResolvedValue(B_DRAFT());
    vi.mocked(getStory).mockResolvedValue({ ...published(), title: 'B view' });
    switchAccount(router.client);
    await screen.findByRole('heading', { name: 'B view' });
    const reads = vi.mocked(getStoryDraft).mock.calls.length;

    gate.resolve({ ...published(), title: 'A late' });
    await expectOnlyB(router.client);
    expect(vi.mocked(getStoryDraft).mock.calls.length).toBe(reads);
  });

  it('drops a discard that finishes afterwards', async () => {
    vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
    const gate = deferred<StoryDraftResponse>();
    vi.mocked(discardStoryDraft).mockReturnValueOnce(gate.promise);
    const user = userEvent.setup();
    const router = renderEditor();
    await screen.findByText('Draft saved. Readers still see the last published version.');
    await user.click(screen.getByRole('button', { name: 'Discard draft' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard draft' }));
    vi.mocked(getStoryDraft).mockResolvedValue(B_DRAFT());
    vi.mocked(getStory).mockResolvedValue({ ...published(), title: 'B view' });
    switchAccount(router.client);
    await screen.findByRole('heading', { name: 'B view' });

    gate.resolve(draft({ title: 'A late', revision: 5 }));
    await expectOnlyB(router.client);
  });

  it('drops a details change that finishes afterwards', async () => {
    const { updateStory } = await import('@/api/stories');
    const gate = deferred<StoryResponse>();
    const spy = vi.spyOn(await import('@/api/stories'), 'updateStory');
    spy.mockReturnValueOnce(gate.promise);
    const { client } = await startThenSwitch(async (user) => {
      await user.click(screen.getByRole('button', { name: 'Details' }));
      const title = screen.getByLabelText('Title');
      await user.clear(title);
      await user.type(title, 'A renamed');
      await user.click(screen.getByRole('button', { name: 'Save details' }));
    });
    gate.resolve({ ...published(), title: 'A late' });
    await expectOnlyB(client);
    expect(updateStory).toBeDefined();
    spy.mockRestore();
  });
});

it('reads the draft back after publishing, so a scene the server dropped shows as published', async () => {
  const onDeletedMap: StoryChapter = {
    ...CHAPTERS[0],
    scene: { map_id: 'map-gone', camera: { center: [0, 0], zoom: 2, bearing: 0, pitch: 0 }, layer_visibility: {} },
  };
  const afterPublish = [{ ...onDeletedMap, scene: null }, CHAPTERS[1]];
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [onDeletedMap, CHAPTERS[1]] } }));
  vi.mocked(getStory).mockResolvedValue(published(CHAPTERS));
  vi.mocked(publishStory).mockResolvedValue(published(afterPublish));
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText('Draft saved. Readers still see the last published version.');

  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: afterPublish } }));
  await user.click(screen.getByRole('button', { name: 'Publish' }));
  expect(await screen.findByText('Published. Readers see this version.')).toBeInTheDocument();
});

it('shows a details change, and the draft as it is on reopening', async () => {
  const spy = vi.spyOn(await import('@/api/stories'), 'updateStory');
  spy.mockResolvedValueOnce({ ...published(), title: 'Renamed' });
  const user = userEvent.setup();
  const router = renderEditor();
  await ready();
  await user.click(screen.getByRole('button', { name: 'Details' }));
  const title = screen.getByLabelText('Title');
  await user.clear(title);
  await user.type(title, 'Renamed');
  await user.click(screen.getByRole('button', { name: 'Save details' }));
  expect(await screen.findByRole('heading', { name: 'Renamed' })).toBeInTheDocument();
  expect(document.title).toBe('Editing Renamed - GeoLens');

  await user.click(screen.getByRole('link', { name: 'View story' }));
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ title: 'Renamed' }));
  await act(() => router.navigate('/stories/s1/edit'));
  expect(await screen.findByRole('heading', { name: 'Renamed' })).toBeInTheDocument();
  spy.mockRestore();
});

it('reads the draft again each time the editor opens', async () => {
  const user = userEvent.setup();
  const router = renderEditor();
  await ready();
  await user.click(screen.getByRole('link', { name: 'View story' }));
  await screen.findByText('reader page');

  vi.mocked(getStoryDraft).mockResolvedValue(draft({ title: 'Changed in another tab' }));
  await act(() => router.navigate('/stories/s1/edit'));
  expect(await screen.findByRole('heading', { name: 'Changed in another tab' })).toBeInTheDocument();
});

describe('a map choice that lands late', () => {
  const scenes = () => lastSavedChapters().map((c) => c.scene?.map_id ?? null);

  async function startChoice(user: ReturnType<typeof userEvent.setup>) {
    const gate = deferred<MapResponse>();
    mapFetch.next = gate.promise;
    await pickMap(user, /^Tracks/);
    return gate;
  }

  it('lands on its chapter after a reorder', async () => {
    const user = userEvent.setup();
    renderEditor();
    await ready();
    const gate = await startChoice(user);
    await user.click(within(screen.getByRole('navigation', { name: 'Chapters' })).getByRole('button', { name: 'Move Opening down' }));
    gate.resolve(MAP);
    await screen.findByRole('button', { name: 'Use current view' });
    saveNow();
    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
    expect(lastSavedChapters().map((c) => c.id)).toEqual(['c2', 'c1']);
    expect(scenes()).toEqual([null, 'map-a']);
  });

  it('is dropped once its chapter is deleted', async () => {
    const user = userEvent.setup();
    renderEditor();
    await ready();
    const gate = await startChoice(user);
    await user.click(within(screen.getByRole('navigation', { name: 'Chapters' })).getByRole('button', { name: 'Delete Opening' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete chapter' }));
    gate.resolve(MAP);
    saveNow();
    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
    expect(scenes()).toEqual([null]);
  });

  it('is dropped once the author moves to another chapter', async () => {
    const user = userEvent.setup();
    renderEditor();
    await ready();
    const gate = await startChoice(user);
    await user.click(within(screen.getByRole('navigation', { name: 'Chapters' })).getByRole('button', { name: /^2\s*Second/ }));
    gate.resolve(MAP);
    await user.type(screen.getByLabelText('Chapter title'), '!');
    saveNow();
    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
    expect(scenes()).toEqual([null, null]);
  });

  it('is dropped once the draft is reloaded from the server', async () => {
    vi.mocked(saveStoryDraft).mockRejectedValueOnce(
      new ApiError('Conflict', 409, { code: 'stale_revision', revision: 9 }),
    );
    const user = userEvent.setup();
    renderEditor();
    await ready();
    await user.click(screen.getByRole('button', { name: 'Add chapter' }));
    saveNow();
    const alert = await screen.findByRole('alert');
    await user.click(within(screen.getByRole('navigation', { name: 'Chapters' })).getByRole('button', { name: /^1\s*Opening/ }));
    const gate = await startChoice(user);
    await user.click(within(alert).getByRole('button', { name: 'Load latest' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Load latest' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    gate.resolve(MAP);
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    await user.type(screen.getByLabelText('Chapter title'), '!');
    saveNow();
    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalledTimes(2));
    expect(scenes()).toEqual([null, null]);
  });
});

it('makes the chapter panel inert while a discard is replacing the draft', async () => {
  vi.mocked(getStory).mockResolvedValue(published([CHAPTERS[0]]));
  const gate = deferred<StoryDraftResponse>();
  vi.mocked(discardStoryDraft).mockReturnValueOnce(gate.promise);
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText('Draft saved. Readers still see the last published version.');
  await user.click(screen.getByRole('button', { name: 'Discard draft' }));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard draft' }));
  expect(screen.getByLabelText('Chapter title').closest('[inert]')).not.toBeNull();
  expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled();

  gate.resolve(draft({ revision: 5, document: { version: 1, chapters: [CHAPTERS[0]] } }));
  expect(await screen.findByText('Published. Readers see this version.')).toBeInTheDocument();
  expect(screen.getByLabelText('Chapter title').closest('[inert]')).toBeNull();
});

it('flags chapters whose map the server could not find and offers to remove the scene', async () => {
  const onMissing: StoryChapter = {
    ...CHAPTERS[0],
    scene: { map_id: 'map-gone', camera: { center: [0, 0], zoom: 2, bearing: 0, pitch: 0 }, layer_visibility: {} },
  };
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [onMissing, CHAPTERS[1]] } }));
  vi.mocked(getStory).mockResolvedValue(published([onMissing, CHAPTERS[1]]));
  vi.mocked(saveStoryDraft).mockRejectedValueOnce(
    new ApiError('Some scenes use maps that weren’t found.', 422, {
      code: 'story_maps_not_found',
      message: 'Some scenes use maps that weren’t found.',
      map_ids: ['map-gone'],
    }),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();

  expect(await screen.findByText(/1 chapter's scene uses a map that wasn't found/)).toBeInTheDocument();
  expect(within(screen.getByRole('navigation', { name: 'Chapters' })).getByText("Its map wasn't found")).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Remove scene' }));
  saveNow();
  await waitFor(() => expect(saveStoryDraft).toHaveBeenCalledTimes(2));
  expect(lastSavedChapters()[0].scene).toBeNull();
});

it('finds a map past the first page through the picker', async () => {
  const page = Array.from({ length: 25 }, (_, i) => ({ id: `m${i}`, name: `Map ${i}`, visibility: 'internal' }));
  vi.mocked(listMaps).mockImplementation(async (params) =>
    params?.skip === 25
      ? ({ maps: [{ id: 'map-a', name: 'Tracks', visibility: 'public' }], total: 26 } as never)
      : ({ maps: page, total: 26 } as never),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const combobox = screen.getByRole('combobox', { name: 'Map' });
  await user.click(combobox);
  await user.keyboard('{ArrowDown}');
  expect(await screen.findByRole('option', { name: /^Map 24/ })).toHaveTextContent('Internal');
  expect(screen.queryByRole('option', { name: /^Tracks/ })).not.toBeInTheDocument();

  // ArrowDown past the last option loads the next page.
  await user.keyboard('{End}');
  for (let i = 0; i < 26; i++) await user.keyboard('{ArrowDown}');
  await user.click(await screen.findByRole('option', { name: /^Tracks/ }));
  await screen.findByRole('button', { name: 'Use current view' });
  expect(vi.mocked(listMaps)).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 25, limit: 25 }));

  await user.type(combobox, 'coast');
  await waitFor(() => expect(vi.mocked(listMaps)).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'coast', skip: 0 })));
  // The server matched these (by description, say), so the list shows them though their names don't contain the query.
  expect(await screen.findByRole('option', { name: /^Map 0/ })).toBeInTheDocument();
});

it('starts the map list from the first page again on reopening', async () => {
  const page = Array.from({ length: 25 }, (_, i) => ({ id: `m${i}`, name: `Map ${i}`, visibility: 'internal' }));
  vi.mocked(listMaps).mockImplementation(async (params) =>
    params?.skip === 25
      ? ({ maps: [{ id: 'map-a', name: 'Tracks', visibility: 'public' }], total: 26 } as never)
      : ({ maps: page, total: 26 } as never),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.click(screen.getByRole('combobox', { name: 'Map' }));
  await user.keyboard('{ArrowDown}');
  await user.click(await screen.findByRole('button', { name: 'Show more maps' }));
  await screen.findByRole('option', { name: /^Tracks/ });
  await user.keyboard('{Escape}');

  vi.mocked(listMaps).mockClear();
  await user.keyboard('{ArrowDown}');
  await screen.findByRole('option', { name: /^Map 0/ });
  expect(screen.queryByRole('option', { name: /^Tracks/ })).not.toBeInTheDocument();
  expect(vi.mocked(listMaps).mock.calls.map(([params]) => params?.skip)).toEqual([0]);
});

it('loads more maps from the button under the list', async () => {
  const page = Array.from({ length: 25 }, (_, i) => ({ id: `m${i}`, name: `Map ${i}`, visibility: 'internal' }));
  vi.mocked(listMaps).mockImplementation(async (params) =>
    params?.skip === 25
      ? ({ maps: [{ id: 'map-a', name: 'Tracks', visibility: 'public' }], total: 26 } as never)
      : ({ maps: page, total: 26 } as never),
  );
  const user = userEvent.setup();
  renderEditor();
  await ready();
  await user.click(screen.getByRole('combobox', { name: 'Map' }));
  await user.keyboard('{ArrowDown}');
  await user.click(await screen.findByRole('button', { name: 'Show more maps' }));
  expect(await screen.findByRole('option', { name: /^Tracks/ })).toBeInTheDocument();
});

describe('document caps', () => {
  it('stops adding chapters at 200', async () => {
    const many = Array.from({ length: 200 }, (_, i) => ({ ...CHAPTERS[0], id: `k${i}`, title: `K${i}` }));
    vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: many } }));
    vi.mocked(getStory).mockResolvedValue(published(many));
    renderEditor();
    await ready();
    expect(screen.getByRole('button', { name: 'Add chapter' })).toBeDisabled();
    expect(screen.getByText('A story can have up to 200 chapters.')).toBeInTheDocument();
  });

  it('stops adding text blocks at 100 per chapter', async () => {
    const blocks = Array.from({ length: 100 }, (_, i) => markdown(`blk-${i}`, ''));
    const crowded = { ...CHAPTERS[0], blocks };
    vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [crowded] } }));
    vi.mocked(getStory).mockResolvedValue(published([crowded]));
    renderEditor();
    await ready();
    expect(screen.getByRole('button', { name: 'Add text block' })).toBeDisabled();
    expect(screen.getByText('A chapter can have up to 100 text blocks.')).toBeInTheDocument();
  });

  it('refuses to save a draft over 2 MB', async () => {
    const big = Array.from({ length: 12 }, (_, i) => ({
      ...CHAPTERS[0],
      id: `big${i}`,
      blocks: Array.from({ length: 10 }, (_, j) => markdown(`big${i}-${j}`, 'x'.repeat(19_000))),
    }));
    vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: big } }));
    vi.mocked(getStory).mockResolvedValue(published(big));
    const user = userEvent.setup();
    renderEditor();
    await ready();
    await user.type(screen.getAllByLabelText('Chapter title')[0], '!');
    expect(await screen.findByText(/larger than the 2 MB/)).toBeInTheDocument();
    saveNow();
    expect(saveStoryDraft).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled();
  });
});

it('links the scene map to the Builder and reloads it once when the author comes back', async () => {
  const withScene: StoryChapter = {
    ...CHAPTERS[0],
    scene: { map_id: 'map-a', camera: { center: [0, 0], zoom: 2, bearing: 0, pitch: 0 }, layer_visibility: {} },
  };
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [withScene] } }));
  vi.mocked(getStory).mockResolvedValue(published([withScene]));
  const user = userEvent.setup();
  const { client } = renderEditor();
  await ready();
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const returnToTab = () => act(() => void document.dispatchEvent(new Event('visibilitychange')));
  returnToTab();
  expect(invalidate).not.toHaveBeenCalled();

  const link = screen.getByRole('link', { name: /Edit map in Builder/ });
  expect(link).toHaveAttribute('href', '/maps/map-a');
  expect(link).toHaveAttribute('target', '_blank');
  link.addEventListener('click', (event) => event.preventDefault());
  await user.click(link);
  returnToTab();
  returnToTab();
  expect(invalidate).toHaveBeenCalledTimes(1);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['map', 'map-a'] });
});

it('focuses a new chapter title, and the next chapter after a delete', async () => {
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const list = screen.getByRole('navigation', { name: 'Chapters' });
  await user.click(within(list).getByRole('button', { name: 'Add chapter' }));
  await waitFor(() => expect(screen.getByLabelText('Chapter title')).toHaveFocus());

  await user.click(within(list).getByRole('button', { name: 'Delete Opening' }));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete chapter' }));
  await waitFor(() => expect(within(list).getByRole('button', { name: /^1\s*Second/ })).toHaveFocus());
});

it('selects the next chapter after deleting the selected one', async () => {
  const third: StoryChapter = { ...CHAPTERS[1], id: 'c3', title: 'Third', blocks: [markdown('b3', 'End')] };
  vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [...CHAPTERS, third] } }));
  vi.mocked(getStory).mockResolvedValue(published([...CHAPTERS, third]));
  const user = userEvent.setup();
  renderEditor();
  await ready();
  const list = screen.getByRole('navigation', { name: 'Chapters' });
  await user.click(within(list).getByRole('button', { name: /^2\s*Second/ }));
  await user.click(within(list).getByRole('button', { name: 'Delete Second' }));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete chapter' }));
  expect(screen.getByLabelText('Chapter title')).toHaveValue('Third');
  expect(screen.getByRole('heading', { level: 2, name: 'Chapter 2 of 2' })).toBeInTheDocument();
});

it('refreshes the stories list after a save', async () => {
  const user = userEvent.setup();
  const { client } = renderEditor();
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  await ready();
  await user.type(screen.getByLabelText('Chapter title'), '!');
  saveNow();
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['stories'] }));
});


describe('image blocks', () => {
  const ASSET = '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60';
  const png = () => new File(['png'], 'river.png', { type: 'image/png' });

  function chapterSection() {
    return screen.getByRole('region', { name: 'Chapter 1 of 2' });
  }

  it('uploads an image into the chapter and saves it once it has alt text', async () => {
    const user = userEvent.setup();
    vi.mocked(uploadStoryImage).mockImplementation(async (_story, _file, onProgress) => {
      onProgress?.(0.5);
      return { id: ASSET, width: 800, height: 400, byte_size: 1000, created_at: '2026-10-29T00:00:00Z' };
    });
    renderEditor();
    await ready();
    const section = chapterSection();
    await user.upload(within(section).getByTestId('story-image-input'), png());

    expect(vi.mocked(uploadStoryImage).mock.lastCall?.[0]).toBe('s1');
    const alt = await within(section).findByRole('textbox', { name: 'Alt text' });
    expect(alt).toBeRequired();
    expect(alt).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getAllByRole('status').some((el) => el.textContent === '1 image needs alt text before you can save.'),
    ).toBe(true);
    expect(screen.getByText('Add alt text to save')).toBeInTheDocument();
    saveNow();
    expect(saveStoryDraft).not.toHaveBeenCalled();

    await user.type(alt, 'A river at dusk');
    await user.type(within(section).getByRole('textbox', { name: 'Caption (optional)' }), 'North');
    saveNow();

    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
    expect(lastSavedChapters()[0].blocks?.at(-1)).toEqual({
      id: expect.any(String),
      type: 'image',
      v: 1,
      title: null,
      asset_id: ASSET,
      config: { alt: 'A river at dusk', caption: 'North' },
    });
  });

  it('refuses a file the server would refuse without sending it, and shows a server refusal', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderEditor();
    await ready();
    const input = within(chapterSection()).getByTestId('story-image-input');

    await user.upload(input, new File(['gif'], 'a.gif', { type: 'image/gif' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only PNG, JPEG and WebP images can be uploaded.');
    const huge = png();
    Object.defineProperty(huge, 'size', { value: 50 * 1024 * 1024 + 1 });
    await user.upload(input, huge);
    expect(await screen.findByRole('alert')).toHaveTextContent('This image is too large.');
    expect(uploadStoryImage).not.toHaveBeenCalled();

    vi.mocked(uploadStoryImage).mockImplementation(async () => {
      throw new ApiError('Other images are being processed. Try again in a moment.', 503);
    });
    await user.upload(input, png());
    expect(await screen.findByRole('alert')).toHaveTextContent('Other images are being processed.');
    expect(within(chapterSection()).queryByRole('textbox', { name: 'Alt text' })).not.toBeInTheDocument();
  });
});

describe('autosave', () => {
  async function editTitle(text: string) {
    fireEvent.change(screen.getByLabelText('Chapter title'), { target: { value: text } });
    await act(async () => {});
  }
  const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  async function readyWithFakeTimers() {
    const router = renderEditor();
    await ready();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    return router;
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it('saves two seconds after the author stops editing, and not before', async () => {
    await readyWithFakeTimers();
    await editTitle('Landfall');
    await advance(1500);
    await editTitle('Landfall 2');
    await advance(1999);
    expect(saveStoryDraft).not.toHaveBeenCalled();
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

    await advance(1);
    expect(saveStoryDraft).toHaveBeenCalledTimes(1);
    expect(saveStoryDraft).toHaveBeenCalledWith('s1', 4, expect.any(Array));
    expect(lastSavedChapters()[0].title).toBe('Landfall 2');
    expect(screen.getByText('Draft saved. Readers still see the last published version.')).toBeInTheDocument();
  });

  it("doesn't save a draft nobody has changed", async () => {
    await readyWithFakeTimers();
    await advance(10_000);
    saveNow();
    expect(saveStoryDraft).not.toHaveBeenCalled();
  });

  it('saves at once when the tab is hidden', async () => {
    await readyWithFakeTimers();
    await editTitle('Landfall');
    const hidden = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('pagehide'));
    });
    hidden.mockRestore();
    expect(saveStoryDraft).toHaveBeenCalledTimes(1);
  });

  it('never runs two saves at once, and sends what was typed meanwhile afterwards', async () => {
    const gate = deferred<StoryDraftResponse>();
    vi.mocked(saveStoryDraft).mockReturnValueOnce(gate.promise);
    await readyWithFakeTimers();
    await editTitle('One');
    await advance(2000);
    await editTitle('Two');
    await advance(5000);
    saveNow();
    expect(saveStoryDraft).toHaveBeenCalledTimes(1);

    gate.resolve(draft({ revision: 5, document: { version: 1, chapters: lastSavedChapters() } }));
    await advance(0);
    await advance(2000);
    expect(saveStoryDraft).toHaveBeenCalledTimes(2);
    expect(saveStoryDraft).toHaveBeenLastCalledWith('s1', 5, expect.any(Array));
    expect(lastSavedChapters()[0].title).toBe('Two');
  });

  it('shows a failed save with a Retry that saves again, and does not retry on its own', async () => {
    vi.mocked(saveStoryDraft).mockRejectedValueOnce(new ApiError('Boom', 500));
    await readyWithFakeTimers();
    await editTitle('Landfall');
    await advance(2000);
    expect(screen.getByText("Couldn't save")).toBeInTheDocument();
    await advance(20_000);
    expect(saveStoryDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await advance(0);
    expect(saveStoryDraft).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByText('Draft saved. Readers still see the last published version.')).toBeInTheDocument();
  });

  it('pauses on a conflict until the author resolves it', async () => {
    vi.mocked(saveStoryDraft).mockRejectedValueOnce(
      new ApiError('Conflict', 409, { code: 'stale_revision', revision: 9 }),
    );
    await readyWithFakeTimers();
    await editTitle('Landfall');
    await advance(2000);
    expect(screen.getByText(/changed somewhere else/)).toBeInTheDocument();

    await editTitle('Landfall again');
    await advance(10_000);
    saveNow();
    expect(saveStoryDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Overwrite with my version' }));
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Overwrite with my version' }),
    );
    await advance(0);
    expect(saveStoryDraft).toHaveBeenLastCalledWith('s1', 9, expect.any(Array));
  });

  it('saves pending edits when the author navigates away, without asking', async () => {
    const router = await readyWithFakeTimers();
    await editTitle('Landfall');
    await act(() => router.navigate('/stories/s1'));
    expect(screen.getByText('reader page')).toBeInTheDocument();
    expect(saveStoryDraft).toHaveBeenCalledWith('s1', 4, expect.any(Array));
    expect(lastSavedChapters()[0].title).toBe('Landfall');
  });

  it('still warns on a tab close while edits wait to save', async () => {
    await readyWithFakeTimers();
    await editTitle('Landfall');
    const close = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(close);
    expect(close.defaultPrevented).toBe(true);
  });

  it("doesn't save the pending edits under another account that signs in", async () => {
    const router = await readyWithFakeTimers();
    await editTitle('Landfall');
    vi.mocked(getStoryDraft).mockResolvedValue(draft({ title: 'B view' }));
    switchAccount(router.client);
    await advance(0);
    expect(saveStoryDraft).not.toHaveBeenCalled();
  });

  it('holds the save while an image uploads, and says why', async () => {
    const gate = deferred<{ id: string; width: number; height: number; byte_size: number; created_at: string }>();
    vi.mocked(uploadStoryImage).mockReturnValueOnce(gate.promise);
    renderEditor();
    await ready();
    const section = screen.getByRole('region', { name: 'Chapter 1 of 2' });
    fireEvent.change(within(section).getByTestId('story-image-input'), {
      target: { files: [new File(['png'], 'river.png', { type: 'image/png' })] },
    });
    await screen.findByRole('progressbar');
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await editTitle('Landfall');
    await advance(10_000);
    saveNow();
    expect(saveStoryDraft).not.toHaveBeenCalled();
    expect(screen.getByText('Waiting for the image upload')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled();
  });

  it('keeps the leave warning for edits that cannot be saved', async () => {
    const user = userEvent.setup();
    renderEditor();
    await ready();
    await typeUnsavedEdit(user);
    await user.click(screen.getByRole('link', { name: 'View story' }));
    expect(await screen.findByRole('alertdialog', { name: 'Leave without saving?' })).toBeInTheDocument();
  });
});

describe('moving blocks', () => {
  it('reorders a chapter\'s blocks, keeps focus on the arrow, and saves the order', async () => {
    const two: StoryChapter = {
      ...CHAPTERS[0],
      blocks: [markdown('b1', 'First'), markdown('b2', 'Second')],
    };
    vi.mocked(getStoryDraft).mockResolvedValue(draft({ document: { version: 1, chapters: [two, CHAPTERS[1]] } }));
    vi.mocked(getStory).mockResolvedValue(published([two, CHAPTERS[1]]));
    const user = userEvent.setup();
    renderEditor();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Move text block 1 down' }));
    expect(screen.getAllByRole('textbox', { name: /^Text block/ }).map((el) => (el as HTMLTextAreaElement).value)).toEqual([
      'Second',
      'First',
    ]);
    expect(screen.getByRole('button', { name: 'Move text block 2 up' })).toHaveFocus();

    saveNow();
    await waitFor(() => expect(saveStoryDraft).toHaveBeenCalled());
    expect(lastSavedChapters()[0].blocks?.map((b) => b.id)).toEqual(['b2', 'b1']);
  });
});

describe('an upload while another chapter is shown', () => {
  it('lands in the chapter it started in', async () => {
    const gate = deferred<{ id: string; width: number; height: number; byte_size: number; created_at: string }>();
    vi.mocked(uploadStoryImage).mockReturnValueOnce(gate.promise);
    const user = userEvent.setup();
    renderEditor();
    await ready();
    const first = screen.getByRole('region', { name: 'Chapter 1 of 2' });
    await user.upload(
      within(first).getByTestId('story-image-input'),
      new File(['png'], 'river.png', { type: 'image/png' }),
    );
    await user.click(document.querySelector<HTMLElement>('[data-chapter-id="c2"] [data-chapter-select]')!);
    expect(screen.getByLabelText('Chapter title')).toHaveValue('Second');

    gate.resolve({ id: '9a3e5c71-2b4d-4f86-8e1a-7c5d3b2f4e60', width: 8, height: 4, byte_size: 10, created_at: '2026-10-29T00:00:00Z' });
    await waitFor(() => expect(screen.getByText('Add alt text to save')).toBeInTheDocument());
    expect(screen.queryByRole('textbox', { name: 'Alt text' })).not.toBeInTheDocument();

    await user.click(document.querySelector<HTMLElement>('[data-chapter-id="c1"] [data-chapter-select]')!);
    expect(await screen.findByRole('textbox', { name: 'Alt text' })).toBeInTheDocument();
  });
});
