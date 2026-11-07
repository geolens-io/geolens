import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { SceneEditor } from '../SceneEditor';
import type { StoryScene } from '@/types/api';

vi.mock('@/hooks/use-maps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/hooks/use-maps')>()),
  useMap: () => ({ data: undefined }),
}));

const scene: StoryScene = {
  map_id: 'map-a',
  camera: { center: [0, 0], zoom: 3, bearing: 0, pitch: 0 },
  layer_visibility: {},
};

function renderEditor(value: StoryScene, edit = vi.fn()) {
  render(
    <SceneEditor chapterId="c1" scene={value} sceneHidden={false} edit={edit} readView={() => null} mapMissing={false} />,
  );
  return edit;
}

beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => undefined;
  Element.prototype.scrollIntoView ??= () => undefined;
});

describe('SceneEditor transition', () => {
  it('shows the story default for a scene with no transition', () => {
    renderEditor(scene);
    expect(screen.getByRole('combobox', { name: 'Transition' })).toHaveTextContent('Story default');
  });

  it("shows a scene's own transition and clears it when the story default is chosen", async () => {
    const user = userEvent.setup();
    const edit = renderEditor({ ...scene, transition: 'cut' });
    const select = screen.getByRole('combobox', { name: 'Transition' });
    expect(select).toHaveTextContent('Cut');
    await user.click(select);
    await user.click(await screen.findByRole('option', { name: 'Story default' }));
    expect(edit).toHaveBeenCalledWith({ type: 'setTransition', chapterId: 'c1', transition: null });
  });
});
