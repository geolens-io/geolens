import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import type { StoryChapter, StoryFrameHost } from '@/types/api';
import { ChapterEditor } from '../ChapterEditor';
import { applyDraftEdit, framesNeedingAttention } from '../story-draft';

let approved: StoryFrameHost[] = [];

vi.mock('@/api/stories', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/stories')>()),
  getStoryFrameHosts: vi.fn(async () => approved),
}));

const EMPTY: StoryChapter = { id: 'c1', title: 'One', scene: null, scene_hidden: false, blocks: [] };

function Editor({ initial = EMPTY }: { initial?: StoryChapter }) {
  const [chapters, setChapters] = useState([initial]);
  return (
    <ChapterEditor
      storyId="s1"
      uploads={{ get: () => ({ progress: null, error: null }), start: vi.fn(), cancelAll: vi.fn(), uploading: false }}
      chapter={chapters[0]}
      index={0}
      edit={(change) => setChapters((c) => applyDraftEdit(c, change))}
      readView={() => null}
      mapMissing={false}
      focusTitle={false}
    />
  );
}

it('turns the embed and video buttons off, and says why, while no host is approved', async () => {
  approved = [];
  render(<Editor />);
  const explanation = await screen.findByText(/Embeds and videos are off until an admin approves/);
  for (const name of ['Add embed', 'Add video']) {
    const button = screen.getByRole('button', { name });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-describedby', explanation.id);
  }
});

it('adds a video block whose address is checked against the approved hosts', async () => {
  approved = [{ host: 'media.example.org', allow_same_origin: false }];
  const user = userEvent.setup();
  render(<Editor />);
  const add = screen.getByRole('button', { name: 'Add video' });
  await waitFor(() => expect(add).toBeEnabled());
  await user.click(add);

  const group = screen.getByRole('group', { name: 'Video 1' });
  expect(group).toHaveTextContent('media.example.org');
  const address = screen.getByRole('textbox', { name: 'Video player address' });
  const title = screen.getByRole('textbox', { name: 'Title' });
  expect(screen.getByText('Write a title before saving.')).toBeInTheDocument();

  await user.type(address, 'http://media.example.org/v/1');
  expect(screen.getByText(/Enter an https address/)).toBeInTheDocument();
  expect(address).toHaveAttribute('aria-invalid', 'true');

  await user.clear(address);
  await user.type(address, 'https://elsewhere.example.com/v/1');
  expect(screen.getByText(/elsewhere\.example\.com isn't an approved site/)).toBeInTheDocument();

  await user.clear(address);
  await user.type(address, 'https://media.example.org/v/1');
  await user.type(title, 'Field visit');
  expect(address).toHaveAttribute('aria-invalid', 'false');
  expect(screen.queryByText(/isn't an approved site|Enter an https address|Write a title/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove video 1' })).toBeInTheDocument();
});

describe('framesNeedingAttention', () => {
  const hosts = [{ host: 'media.example.org', allow_same_origin: false }];
  function chapterWith(...configs: { url: string; title: string }[]): StoryChapter {
    return {
      ...EMPTY,
      blocks: configs.map((config, i) => ({
        id: `00000000-0000-4000-8000-00000000000${i}`,
        type: 'embed' as const,
        v: 1 as const,
        title: null,
        config,
      })),
    };
  }

  it('counts a frame without a title or off the approved hosts', () => {
    const chapter = chapterWith(
      { url: 'https://media.example.org/a', title: 'Chart' },
      { url: 'https://media.example.org/b', title: ' ' },
      { url: 'https://other.example.org/c', title: 'Form' },
      { url: 'http://media.example.org/d', title: 'Old' },
    );
    expect(framesNeedingAttention([chapter], hosts)).toBe(3);
    expect(framesNeedingAttention([chapter], [])).toBe(4);
  });

  it('checks only the address shape while the host list loads', () => {
    const chapter = chapterWith({ url: 'https://other.example.org/c', title: 'Form' });
    expect(framesNeedingAttention([chapter], undefined)).toBe(0);
  });
});
