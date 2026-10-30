import { test, expect, type APIRequestContext, type Page } from './helpers/session';
import { authHeaders, createMap, deleteMap } from './helpers/maps';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const RUN = Date.now().toString(36);
const STORY_TITLE = `E2E Story ${RUN}`;
const MAPS = {
  first: `E2E Story Map A ${RUN}`,
  second: `E2E Story Map B ${RUN}`,
  private: `E2E Story Map Private ${RUN}`,
};

// A 96x64 PNG, inline because the repository ignores *.png outside asset folders.
const IMAGE_FIXTURE = {
  name: 'story-image.png',
  mimeType: 'image/png',
  buffer: Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAGAAAABACAIAAABqVuVZAAAAiElEQVR42u3bMRHAIAxA0aRXIZWApI5IqAQkMFZSJaGAoSPc+3sG3iUjed1vaN6BABAgQIAAAQIESIAAAQIECNBenX8HvtpWf3Ppjw1yYoAAAQIESIAAAQIECBAgQIAECBAgQIAAAQIkQIAAAQIECBAgRaQPdTYIECBAgAABAiRAgAABAgRorwYZuQXBxP0bQwAAAABJRU5ErkJggg==',
    'base64',
  ),
};
const IMAGE_ALT = 'A blue field with a yellow band';

const mapIds: Record<keyof typeof MAPS, string> = { first: '', second: '', private: '' };
let storyId = '';

async function createPublicMap(request: APIRequestContext, name: string): Promise<string> {
  const id = await createMap(request, name);
  const updated = await request.put(`${BASE_URL}/api/maps/${id}`, {
    headers: authHeaders(),
    data: { visibility: 'public' },
  });
  expect(updated.ok(), `Publish map failed: ${updated.status()}`).toBe(true);
  return id;
}

async function addChapter(page: Page, title: string, text: string, mapName: string) {
  await page.getByRole('navigation', { name: 'Chapters' }).getByRole('button', { name: 'Add chapter' }).click();
  await page.getByLabel('Chapter title').fill(title);
  await page.getByLabel('Text block 1').fill(text);
  await page.getByRole('combobox', { name: 'Map' }).fill(mapName);
  await page.getByRole('option', { name: new RegExp(`^${mapName}`) }).click();
  await expect(page.getByRole('button', { name: 'Use current view' })).toBeVisible();
}

test.describe.serial('Stories', () => {
  test.beforeAll(async ({ playwright }) => {
    const request = await playwright.request.newContext();
    try {
      mapIds.first = await createPublicMap(request, MAPS.first);
      mapIds.second = await createPublicMap(request, MAPS.second);
      mapIds.private = await createMap(request, MAPS.private);
    } finally {
      await request.dispose();
    }
  });

  test.afterAll(async ({ playwright }) => {
    const request = await playwright.request.newContext();
    try {
      if (storyId) await request.delete(`${BASE_URL}/api/stories/${storyId}`, { headers: authHeaders() });
      for (const id of Object.values(mapIds)) if (id) await deleteMap(request, id);
    } finally {
      await request.dispose();
    }
  });

  test('an author writes a story across two maps and publishes it', async ({ page }) => {
    await page.goto('/maps?type=stories');
    await page.getByRole('button', { name: 'New story' }).click();
    await page.getByLabel('Title').fill(STORY_TITLE);
    await page.getByRole('button', { name: 'Create and edit' }).click();
    await page.waitForURL(/\/stories\/[0-9a-f-]+\/edit$/);
    storyId = page.url().match(/\/stories\/([0-9a-f-]+)\/edit$/)![1];

    await addChapter(page, 'Where it starts', 'The **first** chapter.', MAPS.first);
    await addChapter(page, 'Where it ends', 'The second chapter.', MAPS.second);

    await page.getByRole('button', { name: 'Details' }).click();
    await page.getByRole('combobox', { name: 'Who can read it' }).click();
    await page.getByRole('option', { name: 'Public' }).click();
    await page.getByRole('button', { name: 'Save details' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();

    await page.getByRole('button', { name: 'Publish' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Published. Readers see this version.' })).toBeVisible();
  });

  test('an author adds an image and a cover, then publishes them', async ({ page }) => {
    await page.goto(`/stories/${storyId}/edit`);
    await expect(page.getByRole('heading', { level: 1, name: STORY_TITLE })).toBeVisible();
    const chapter = page.getByRole('region', { name: /^Chapter 1 of/ });
    await chapter.getByTestId('story-image-input').setInputFiles(IMAGE_FIXTURE);
    const alt = chapter.getByRole('textbox', { name: 'Alt text' });
    await expect(alt).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    await alt.fill(IMAGE_ALT);
    await expect(chapter.getByRole('img', { name: IMAGE_ALT })).toBeVisible();

    await page.getByRole('button', { name: 'Details' }).click();
    const details = page.getByRole('dialog');
    await details.getByTestId('story-image-input').setInputFiles(IMAGE_FIXTURE);
    await expect(details.getByRole('img', { name: 'Cover image preview' })).toBeVisible();
    await details.getByRole('button', { name: 'Save details' }).click();
    await expect(details).toBeHidden();

    await page.getByRole('button', { name: 'Publish' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Published. Readers see this version.' })).toBeVisible();
  });

  test.describe('signed out', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('an anonymous reader sees the story image and the cover', async ({ page }) => {
      await page.goto(`/stories/${storyId}`);
      const image = page.getByRole('img', { name: IMAGE_ALT });
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      await expect(page.locator('header img[alt=""]').first()).toBeVisible();
    });

    test('an anonymous reader opens the published story', async ({ page }) => {
      await page.goto(`/stories/${storyId}`);
      await expect(page.getByRole('heading', { level: 1, name: STORY_TITLE })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: 'Where it starts' })).toBeVisible();
      await expect(page.getByText('first', { exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: 'Where it ends' })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Edit' })).toHaveCount(0);
    });
  });

  test('publishing a public story with a private map is refused and names the map', async ({ page }) => {
    await page.goto(`/stories/${storyId}/edit`);
    await expect(page.getByRole('heading', { level: 1, name: STORY_TITLE })).toBeVisible();
    await addChapter(page, 'Behind a door', 'Only some can see this map.', MAPS.private);

    await page.getByRole('button', { name: 'Publish' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Publishing was refused' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('link', { name: MAPS.private })).toHaveAttribute('href', `/maps/${mapIds.private}`);
    await dialog.getByRole('button', { name: 'Close' }).click();
  });
});
