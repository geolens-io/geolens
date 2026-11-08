import { test, expect, type Page } from './helpers/session';
import { authHeaders, createMap, deleteMap } from './helpers/maps';
import { deleteDataset, seedDataset, type SeededDataset } from './helpers/catalog';
import {
  cameraDistance,
  createPublishedStory,
  deleteStory,
  dragMap,
  readMapCamera,
  waitForStoryMap,
  type ChapterSpec,
  type SceneCamera,
  type StorySettingsSpec,
} from './helpers/stories';

const RUN = Date.now().toString(36);
const FIRST: SceneCamera = { center: [-74, 40.7], zoom: 9 };
const SECOND: SceneCamera = { center: [-100, 40], zoom: 4 };
const THIRD: SceneCamera = { center: [-120, 37], zoom: 6 };
// The longest a transition runs.
const FLY_MAX_MS = 2_500;

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
let mapId = '';
let dataset: SeededDataset | null = null;
const storyIds: string[] = [];

test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  try {
    mapId = await createMap(request, `E2E Reader Map ${RUN}`);
    dataset = await seedDataset('E2E Reader Dataset');
    const layer = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      headers: authHeaders(),
      data: { dataset_id: dataset.id },
    });
    expect(layer.ok(), `Add layer failed: ${layer.status()}`).toBe(true);
  } finally {
    await request.dispose();
  }
});

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  try {
    for (const id of storyIds) await deleteStory(request, id);
    if (mapId) await deleteMap(request, mapId);
    if (dataset) await deleteDataset(dataset.id, dataset.title);
  } finally {
    await request.dispose();
  }
});

async function publishStory(
  playwright: { request: { newContext(): Promise<import('./helpers/session').APIRequestContext> } },
  name: string,
  chapters: Omit<ChapterSpec, 'mapId'>[],
  settings?: StorySettingsSpec,
): Promise<string> {
  const request = await playwright.request.newContext();
  try {
    const id = await createPublishedStory(
      request,
      `E2E ${name} ${RUN}`,
      chapters.map((chapter) => ({ ...chapter, mapId })),
      settings,
    );
    storyIds.push(id);
    return id;
  } finally {
    await request.dispose();
  }
}

const chaptersNav = (page: Page) => page.getByRole('navigation', { name: 'Story chapters' });
const chapterPanel = (page: Page) => page.getByRole('region', { name: 'Story chapters' });

async function openChapter(page: Page, title: string) {
  await chaptersNav(page).getByRole('button', { name: title }).click();
}

test.describe('story transitions', () => {
  const chapters = (second: ChapterSpec['transition']) => [
    { title: 'Start', camera: FIRST },
    { title: 'Middle', camera: SECOND, transition: second },
    { title: 'End', camera: THIRD },
  ];

  test('a Cut chapter jumps to its camera at once', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'Cut', chapters('cut'), { navigation: true });
    await page.goto(`/stories/${id}`);
    await waitForStoryMap(page, FIRST);

    await openChapter(page, 'Middle');
    await expect.poll(async () => cameraDistance(await readMapCamera(page), SECOND), { timeout: 500 }).toBeLessThan(0.05);
  });

  test('a Fly chapter reaches its camera within the transition time', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'Fly', chapters('fly'), { navigation: true });
    await page.goto(`/stories/${id}`);
    await waitForStoryMap(page, FIRST);

    await openChapter(page, 'Middle');
    expect(cameraDistance(await readMapCamera(page), SECOND)).toBeGreaterThan(1);
    await expect
      .poll(async () => cameraDistance(await readMapCamera(page), SECOND), { timeout: FLY_MAX_MS + 1_500 })
      .toBeLessThan(0.05);
  });

  test('the back button appears after a drag and restores the chapter view', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'Return', chapters('cut'), { navigation: true });
    await page.goto(`/stories/${id}`);
    await waitForStoryMap(page, FIRST);
    const back = page.getByRole('button', { name: "Back to this chapter's view" });
    await expect(back).toBeHidden();

    await openChapter(page, 'Middle');
    await waitForStoryMap(page, SECOND);
    await expect(back).toBeHidden();

    await dragMap(page);
    await expect(back).toBeVisible();
    expect(cameraDistance(await readMapCamera(page), SECOND)).toBeGreaterThan(0.05);

    await back.click();
    await expect
      .poll(async () => cameraDistance(await readMapCamera(page), SECOND), { timeout: FLY_MAX_MS + 1_500 })
      .toBeLessThan(0.05);
    await expect(back).toBeHidden();
  });

  test('under reduced motion a Fly chapter cuts', async ({ page, playwright }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const id = await publishStory(playwright, 'Reduced', chapters('fly'), { navigation: true });
    await page.goto(`/stories/${id}`);
    await waitForStoryMap(page, FIRST);

    await openChapter(page, 'Middle');
    await expect.poll(async () => cameraDistance(await readMapCamera(page), SECOND), { timeout: 500 }).toBeLessThan(0.05);
  });
});

test.describe('story navigation bar', () => {
  const chapters = [
    { title: 'Alpha', camera: FIRST, paragraphs: 14 },
    { title: 'Bravo', camera: SECOND, paragraphs: 14 },
    { title: 'Charlie', camera: THIRD, paragraphs: 14 },
  ];

  test('lists the chapters and follows the reader as they scroll', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'Nav', chapters, { navigation: true });
    await page.goto(`/stories/${id}`);
    const nav = chaptersNav(page);
    await expect(nav.getByRole('button')).toHaveText(['Alpha', 'Bravo', 'Charlie']);
    await expect(nav.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-current', 'step');

    await chapterPanel(page).hover();
    await expect
      .poll(
        async () => {
          await page.mouse.wheel(0, 250);
          return nav.getByRole('button', { name: 'Bravo' }).getAttribute('aria-current');
        },
        { timeout: 15_000 },
      )
      .toBe('step');
    await expect(nav.getByRole('button', { name: 'Alpha' })).not.toHaveAttribute('aria-current', 'step');

    await openChapter(page, 'Charlie');
    await expect(nav.getByRole('button', { name: 'Charlie' })).toHaveAttribute('aria-current', 'step');
  });

  test('is absent when navigation is off', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'NoNav', chapters);
    await page.goto(`/stories/${id}`);
    await expect(chapterPanel(page)).toBeVisible();
    await expect(chaptersNav(page)).toHaveCount(0);
  });

  test('collapses into a menu on a phone that Escape closes', async ({ page, playwright }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const id = await publishStory(playwright, 'NavPhone', chapters, { navigation: true });
    await page.goto(`/stories/${id}`);
    const menu = chaptersNav(page).getByRole('button', { name: 'Chapters' });
    await expect(chaptersNav(page).getByRole('button', { name: 'Bravo' })).toHaveCount(0);

    await menu.click();
    const sheet = page.getByRole('dialog');
    await expect(sheet.getByRole('button', { name: 'Bravo' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    await expect(menu).toBeFocused();
  });
});

test.describe('story floating layout', () => {
  const chapters = [
    { title: 'Alpha', camera: FIRST },
    { title: 'Bravo', camera: SECOND },
  ];

  test('puts the chapter panel over a full-width map on the right', async ({ page, playwright }) => {
    const id = await publishStory(playwright, 'Floating', chapters, { layout: 'floating', panel_position: 'right' });
    await page.goto(`/stories/${id}`);
    const panel = chapterPanel(page);
    await expect(panel).toBeVisible();
    await waitForStoryMap(page, FIRST);

    const viewport = page.viewportSize()!;
    const map = (await page.locator('#map-viewport').boundingBox())!;
    const box = (await panel.boundingBox())!;
    expect(map.width).toBeGreaterThanOrEqual(viewport.width - 1);
    expect(box.x).toBeGreaterThan(viewport.width / 2);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);

    const launcher = page.getByRole('button', { name: 'Map data' });
    await expect(launcher).toBeVisible();
    const data = (await launcher.boundingBox())!;
    const overlaps = data.x < box.x + box.width && data.x + data.width > box.x && data.y < box.y + box.height && data.y + data.height > box.y;
    expect(overlaps, 'The Map data button sits under the story panel').toBe(false);

    await expect(launcher).toBeEnabled();
    await launcher.click();
    const docked = page.getByRole('region', { name: 'Map data' });
    await expect(docked).toBeVisible();
    const dockedBox = (await docked.boundingBox())!;
    const topmost = await docked.evaluate((el, [x, y]) => el.contains(document.elementFromPoint(x, y)), [
      box.x + box.width / 2,
      dockedBox.y + 8,
    ]);
    expect(topmost, 'The story panel covers the Map data panel').toBe(true);
  });

  test('scrolls a wide code block inside the chapter, not the whole panel', async ({ page, playwright }) => {
    const wide = `https://example.com/api/collections/${'a'.repeat(160)}/items`;
    const id = await publishStory(
      playwright,
      'FloatingCode',
      [{ title: 'Code', camera: FIRST, text: `Before.\n\n\`\`\`\n${wide}\n\`\`\`\n\nAfter.` }],
      { layout: 'floating', panel_position: 'right' },
    );
    await page.goto(`/stories/${id}`);
    const panel = chapterPanel(page);
    await expect(panel.locator('pre')).toBeVisible();
    const overflow = await panel.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow, 'The chapter panel scrolls sideways').toBeLessThanOrEqual(1);
  });

  test('keeps the stepper on a phone', async ({ page, playwright }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const id = await publishStory(playwright, 'FloatingPhone', chapters, { layout: 'floating', panel_position: 'right' });
    await page.goto(`/stories/${id}`);
    const stepper = page.getByRole('group', { name: 'Chapters' });
    await expect(stepper).toBeVisible();
    await expect(stepper.getByRole('button', { name: 'Next' })).toBeVisible();
    await expect(chapterPanel(page)).toHaveCount(0);
  });
});

test.describe('story reader theme', () => {
  const chapters = [{ title: 'Alpha', camera: FIRST }];
  const rootClass = (page: Page) => page.evaluate(() => document.documentElement.className);

  test('a dark story renders dark while the editor keeps the reader\'s own theme', async ({ page, playwright }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => localStorage.setItem('geolens-theme', 'light'));
    const id = await publishStory(playwright, 'Dark', chapters, { theme: 'dark' });

    await page.goto(`/stories/${id}`);
    await expect(page.getByRole('heading', { level: 2, name: 'Alpha' })).toBeVisible();
    await expect.poll(() => rootClass(page)).toContain('dark');

    // An in-app link keeps the document, so the theme provider's cleanup is what restores the theme.
    await page.getByRole('link', { name: 'Edit' }).click();
    await page.waitForURL(/\/stories\/[0-9a-f-]+\/edit$/);
    await expect(page.getByRole('button', { name: 'Publish' })).toBeVisible();
    await expect.poll(() => rootClass(page)).not.toContain('dark');
    expect(await page.evaluate(() => localStorage.getItem('geolens-theme'))).toBe('light');
  });

  test('a story that follows leaves the reader on their theme', async ({ page, playwright }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => localStorage.setItem('geolens-theme', 'light'));
    const id = await publishStory(playwright, 'Follow', chapters, { theme: 'follow' });

    await page.goto(`/stories/${id}`);
    await expect(page.getByRole('heading', { level: 2, name: 'Alpha' })).toBeVisible();
    expect(await rootClass(page)).not.toContain('dark');
  });
});
